
from collections import deque
from datetime import datetime
import time

# Patch pkg_resources before importing adbutils and uiautomator2
from module.device.pkg_resources import get_distribution
# Just avoid being removed by import optimization
_ = get_distribution

from module.base.utils import get_color
from module.device.env import IS_WINDOWS
from module.base.timer import Timer
from module.config.utils import get_server_next_update
from module.device.app_control import AppControl
from module.device.control import Control
from module.device.platform2 import Platform
from module.device.screenshot import Screenshot
from module.exception import (GameNotRunningError,
                              GameStuckError,
                              GameTooManyClickError,
                              RequestHumanTakeover,
                              EmulatorNotRunningError)
from module.logger import logger


class Device(Platform, Screenshot, Control, AppControl):
    _screen_size_checked = False
    detect_record = set()
    click_record = deque(maxlen=15)
    stuck_timer = Timer(60, count=60).start()
    stuck_timer_long = Timer(300, count=300).start()
    stuck_long_wait_list = ['BATTLE_STATUS_S', 'PAUSE', 'LOGIN_CHECK', 'PREPARE_BEFORE_BATTLE']

    def __init__(self, *args, **kwargs):
        for trial in range(4):
            try:
                super().__init__(*args, **kwargs)
                break
            except EmulatorNotRunningError:
                if trial >= 3:
                    logger.critical('[设备-平台] 模拟器启动失败 3 次')
                    raise RequestHumanTakeover
                # Try to start emulator
                if self.emulator_instance is not None:
                    self.emulator_start()
                else:
                    logger.critical(
                        f'[设备-平台] 未找到序列号为 "{self.config.Emulator_Serial}" 的模拟器，'
                        f'请设置正确的序列号'
                    )
                    raise RequestHumanTakeover

        # Auto-fill emulator info
        if IS_WINDOWS and self.config.script.device.emulatorinfo_type == 'auto':
            _ = self.emulator_instance

        self.screenshot_interval_set()
        self._image_batch_cache_frame_id: str | None = None
        self._image_batch_cache: dict[int, dict] = {}

        # Auto-select the fastest screenshot method
        if self.config.script.device.screenshot_method == 'auto':
            self.run_simple_screenshot_benchmark()

    def reset_image_batch_cache(self, frame_id: str | None = None) -> None:
        self._image_batch_cache_frame_id = frame_id
        self._image_batch_cache = {}

    def invalidate_image_batch_cache(self) -> None:
        self.reset_image_batch_cache()

    def get_image_batch_cache(self, target, frame_id: str | None = None) -> dict | None:
        active_frame_id = self.image_frame_id if frame_id is None else frame_id
        if active_frame_id is None:
            return None
        if self._image_batch_cache_frame_id != active_frame_id:
            return None
        return self._image_batch_cache.get(id(target))

    def update_image_batch_cache(self, targets: list, results: list[dict], frame_id: str | None = None) -> None:
        active_frame_id = self.image_frame_id if frame_id is None else frame_id
        if active_frame_id is None:
            return
        if self._image_batch_cache_frame_id != active_frame_id:
            self.reset_image_batch_cache(active_frame_id)
        for target, result in zip(targets, results):
            self._image_batch_cache[id(target)] = dict(result)

    def run_simple_screenshot_benchmark(self):
        """
        Perform a screenshot method benchmark, test 3 times on each method.
        The fastest one will be set into config.
        """
        logger.info('[设备-截图] 开始截图方法基准测试')
        # Check resolution first
        # self.resolution_check_uiautomator2()
        # Perform benchmark
        from module.daemon.benchmark import Benchmark
        bench = Benchmark(config=self.config, device=self)
        method = bench.run_simple_screenshot_benchmark()
        # Set
        self.config.script.device.screenshot_method = method
        self.config.save()

    def handle_night_commission(self, daily_trigger='21:00', threshold=30):
        """
        Args:
            daily_trigger (int): Time for commission refresh.
            threshold (int): Seconds around refresh time.

        Returns:
            bool: If handled.
        """
        update = get_server_next_update(daily_trigger=daily_trigger)
        now = datetime.now()
        diff = (update.timestamp() - now.timestamp()) % 86400
        if threshold < diff < 86400 - threshold:
            return False

        # if GET_MISSION.match(self.image, offset=True):
        #     logger.info('Night commission appear.')
        #     self.click(GET_MISSION)
        #     return True

        return False

    def screenshot(self):
        """
        Returns:
            np.ndarray:
        """
        self.stuck_record_check()

        try:
            super().screenshot()
        except RequestHumanTakeover as e:
            raise RequestHumanTakeover

        if self.handle_night_commission():
            super().screenshot()

        self.reset_image_batch_cache(self.image_frame_id)
        return self.image

    def release_during_wait(self):
        # Scrcpy server is still sending video stream,
        # stop it during wait
        # self.config.script.device.screenshot_method = 'scrcpy'
        if self.config.script.device.screenshot_method == 'scrcpy':
            self._scrcpy_server_stop()
        if self.config.Emulator_ScreenshotMethod == 'nemu_ipc':
            self.nemu_ipc_release()

    def stuck_record_add(self, button):
        """
        当你要设置这个时候检测为长时间的时候，你需要在这里添加
        如果取消后，需要在`stuck_record_clear`中清除
        :param button:
        :return:
        """
        self.detect_record.add(str(button))
        logger.info(f'[设备-控制] 添加卡住检测记录: {button}')

    def stuck_record_clear(self):
        self.detect_record = set()
        self.stuck_timer.reset()
        self.stuck_timer_long.reset()

    def stuck_record_check(self):
        """
        Raises:
            GameStuckError:
        """
        reached = self.stuck_timer.reached()
        reached_long = self.stuck_timer_long.reached()

        if not reached:
            return False
        if not reached_long:
            for button in self.stuck_long_wait_list:
                if button in self.detect_record:
                    return False

        logger.warning('[设备-控制] 等待时间过长')
        logger.warning(f'[设备-控制] 正在等待: {self.detect_record}')
        self.stuck_record_clear()

        if self.app_is_running():
            raise GameStuckError(f'Wait too long')
        else:
            raise GameNotRunningError('Game died')

    def handle_control_check(self, button):
        self.stuck_record_clear()
        self.click_record_add(button)
        self.click_record_check()

    def click_record_add(self, button):
        self.click_record.append(str(button))

    def click_record_clear(self):
        self.click_record.clear()

    def click_record_remove(self, button):
        """
        Remove a button from `click_record`

        Args:
            button (Button):

        Returns:
            int: Number of button removed
        """
        removed = 0
        for _ in range(self.click_record.maxlen):
            try:
                self.click_record.remove(str(button))
                removed += 1
            except ValueError:
                # Value not in queue
                break

        return removed

    def click_record_check(self):
        """
        Raises:
            GameTooManyClickError:
        """
        count = {}
        for key in self.click_record:
            count[key] = count.get(key, 0) + 1
        count = sorted(count.items(), key=lambda item: item[1], reverse=True)
        if count[0][1] >= 10:
            logger.warning(f'[设备-控制] 同一按钮点击次数过多: {count[0][0]}')
            logger.warning(f'[设备-控制] 点击历史: {[str(prev) for prev in self.click_record]}')
            self.click_record_clear()
            raise GameTooManyClickError(f'Too many click for a button: {count[0][0]}')
        if len(count) >= 2 and count[0][1] >= 6 and count[1][1] >= 6:
            logger.warning(f'[设备-控制] 两个按钮之间点击次数过多: {count[0][0]}, {count[1][0]}')
            logger.warning(f'[设备-控制] 点击历史: {[str(prev) for prev in self.click_record]}')
            self.click_record_clear()
            raise GameTooManyClickError(f'Too many click between 2 buttons: {count[0][0]}, {count[1][0]}')

    def disable_stuck_detection(self):
        """
        Disable stuck detection and its handler. Usually uses in semi auto and debugging.
        """
        logger.info('[设备-控制] 已禁用卡住检测')

        def empty_function(*arg, **kwargs):
            return False

        self.click_record_check = empty_function
        self.stuck_record_check = empty_function

    def app_start(self):
        if not self.config.script.error.handle_error:
            logger.critical('[设备-平台] HandleError 已禁用，不执行应用停止/启动')
            logger.critical('请启用 Alas.Error.HandleError 或手动登录阴阳师')
            raise RequestHumanTakeover
        super().app_start()
        self.stuck_record_clear()
        self.click_record_clear()

    def app_stop(self):
        if not self.config.script.error.handle_error:
            logger.critical('[设备-平台] HandleError 已禁用，不执行应用停止/启动')
            logger.critical('请启用 Alas.Error.HandleError 或手动登录阴阳师')
            raise RequestHumanTakeover
        super().app_stop()
        self.stuck_record_clear()
        self.click_record_clear()

    def wait_app_start_ready(self, timeout: float = 15.0, interval: float = 0.5) -> None:
        """
        在启动app后，等待包名切换成功且画面脱离纯黑状态。

        这里直接调用底层截图方法做静默探测，避免app刚启动时首屏黑场造成成批告警。

        Args:
            timeout: 最大等待秒数。
            interval: 每轮探测的间隔秒数。
        """
        deadline = time.time() + timeout
        screenshot_method = self.screenshot_methods.get(
            self.config.script.device.screenshot_method,
            self.screenshot_adb
        )

        while time.time() < deadline:
            if not self.app_is_running():
                time.sleep(interval)
                continue

            try:
                image = screenshot_method()
            except Exception as e:
                logger.info(f'[设备-平台] 等待游戏启动就绪: 截图探测失败: {e}')
                time.sleep(interval)
                continue

            color = get_color(image, area=(0, 0, 1280, 720))
            if sum(color) >= 1:
                logger.info(f'[设备-平台] 游戏启动就绪，画面颜色: {color}')
                return

            time.sleep(interval)

        logger.info('[设备-平台] 等待游戏启动就绪超时，继续登录流程')


if __name__ == "__main__":
    device = Device(config="oas1")
    # cv2.imshow("imgSrceen", device.screenshot())  # 显示
    # cv2.waitKey(0)
    # cv2.destroyAllWindows()
