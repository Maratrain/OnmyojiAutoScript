import timeit
import numpy as np
from datetime import datetime

from module.base.timer import Timer
from module.device.handle import Handle, WindowNode, handle_num2title, handle_title2num, is_handle_valid
from module.logger import logger
from module.base.utils import point2str
from module.exception import RequestHumanTakeover, GameStuckError
from tasks.base_task import BaseTask

from tasks.Hyakkiyakou.config import ScreenshotMethod, ControlMethod

def image_black(img) -> bool:
    for y, x in [(0, 0), (719, 1279), (719, 0), (0, 1279)]:
        if np.all(img[y, x] != 0):
            return False
    return True


class HyaDevice(BaseTask):
    """
    这个类主要是是优化截屏点击速度
    1. 使用特别的method
    2. 扔掉中间的冗余校验
    3. 考虑JIT加速
    我宣布世界上最好的 Linux 系统是 Windows
    """
    hya_screenshot_interval = Timer(0.2)  # 300ms
    hya_fs_check_timer = Timer(3 * 60)  # 五分钟跑不完就应该是出问题了

    def _ensure_root_node(self) -> None:
        """Ensure root_node is initialized on the Device.

        Handle.__init__ returns early without creating root_node when
        config.script.device.handle is empty. This rebuilds it on demand.
        """
        if hasattr(self.device, 'root_node'):
            return
        from module.config.config import Config
        root_handle = self.device.config.script.device.handle
        if not root_handle:
            logger.warning('[百鬼夜行] 设备句柄配置为空，无法构建 root_node')
            return
        root_handle_title = ''
        root_handle_num = 0
        if root_handle == 'auto':
            logger.info('[百鬼夜行] 句柄为 auto，正在搜索模拟器窗口')
            window_list = Handle.all_windows()
            root_handle_title = Handle.auto_handle_title(window_list)
            root_handle_num = handle_title2num(root_handle_title)
        else:
            try:
                root_handle_num = int(root_handle)
                if is_handle_valid(root_handle_num):
                    root_handle_title = handle_num2title(root_handle_num)
            except ValueError:
                if handle_title2num(root_handle) != 0:
                    root_handle_num = handle_title2num(root_handle)
                    root_handle_title = root_handle
        self.device.root_handle_title = root_handle_title
        self.device.root_handle_num = root_handle_num
        self.device.root_node = WindowNode(name=root_handle_title, num=root_handle_num)
        Handle.handle_tree(root_handle_num, self.device.root_node)
        logger.info(f'[百鬼夜行] root_node 已初始化: title={root_handle_title}, num={root_handle_num}')

    def fast_screenshot(self, screenshot: ScreenshotMethod):
        self._ensure_root_node()
        self.hya_screenshot_interval.wait()
        self.hya_screenshot_interval.reset()
        if hasattr(self.device, 'root_node'):
            self.device.image = self.device.screenshot_window_background() if screenshot == ScreenshotMethod.WINDOW_BACKGROUND else self.device.screenshot_nemu_ipc()
        else:
            logger.warning('[百鬼夜行] root_node 不可用，回退到标准截图')
            self.device.screenshot()
        self.device.image_frame_id = None
        if image_black(self.device.image):
            logger.error('[百鬼夜行] 截图图像全黑，请重试')
            raise RequestHumanTakeover('Screenshot image is black, try again')
        if self.hya_fs_check_timer.reached():
            logger.error('[百鬼夜行] 快速截图检查计时器已达上限')
            logger.error('[百鬼夜行] 五分钟仍未结束，游戏可能卡住，请检查游戏')
            raise GameStuckError
        if self.config.script.error.save_error:
            self.device.screenshot_deque.append({'time': datetime.now(), 'image': self.device.image})
        return self.device.image

    def fast_click(self, x: int, y: int, control_method: ControlMethod = ControlMethod.WINDOW_MESSAGE) -> None:
        self._ensure_root_node()
        logger.info(
            '点击 %s @ %s' % (point2str(x, y), 'Click')
        )
        if not hasattr(self.device, 'root_node'):
            logger.warning('[百鬼夜行] root_node 不可用，回退到标准点击')
            self.device.click(x, y)
            return
        if control_method == ControlMethod.MINITOUCH:
            try:
                self.device.click_minitouch(x=x, y=y)
            except AttributeError:
                logger.warning('[百鬼夜行] click_minitouch 失败，回退到标准点击')
                self.device.click(x, y)
        else:
            try:
                self.device.click_window_message(x=x, y=y, fast=True)
            except AttributeError:
                logger.warning('[百鬼夜行] click_window_message 失败，回退到标准点击')
                self.device.click(x, y)

    def set_fast_screenshot_interval(self, interval: float):
        """

        @param interval: ms
        @return:
        """
        self.hya_screenshot_interval = Timer(interval / 1000.)


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    hd = HyaDevice(c, d)

    # def screenshot():
    #     global hd
    #     # hd.fast_screenshot()
    #     hd.fast_click(420, 370)
    #     hd.fast_click(750, 400)
    # execution_time = timeit.timeit(screenshot, number=50)
    # print(f"执行总的时间: {execution_time * 1000} ms")

    from tasks.Hyakkiyakou.config import ScreenshotMethod
    hd.fast_screenshot(screenshot=ScreenshotMethod.WINDOW_BACKGROUND)
