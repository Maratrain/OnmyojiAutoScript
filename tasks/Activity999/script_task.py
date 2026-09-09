import time

from module.base.timer import Timer
from module.exception import RequestHumanTakeover, TaskEnd
from module.logger import logger
from module.base.random_delay import (
    BATTLE_SETTLEMENT_DELAY,
    CONTINUOUS_CONFIRM_DELAY,
    FIRST_OPERATION_DELAY,
    lognormal_delay,
)
from tasks.Activity999.assets import Activity999Assets
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main


class ScriptTask(GeneralBattle, GameUi, Activity999Assets):
    """Run the 999 activity elite challenge continuously."""

    minimum_click_interval = CONTINUOUS_CONFIRM_DELAY
    recognition_click_delay = FIRST_OPERATION_DELAY
    PAGE_WAIT_TIMEOUT = 15
    # 从活动首页点"战斗"到回响地图加载完成, 中间要过鬼王出场动画, 放宽到 30 秒
    BATTLE_MAP_TIMEOUT = 30

    def is_activity_battle_win(self):
        """Recognize both normal and reward-covered activity settlement pages."""
        return (self.appear(self.I_ACTIVITY_999_REWARD_WIN)
                or self.appear(self.I_ACTIVITY_999_BATTLE_WIN, threshold=0.68)
                or self.appear(self.I_ACTIVITY_999_SETTLEMENT_CONTINUE))

    def is_activity_battle_result_closed(self):
        """Confirm settlement closed by recognizing a real activity landing page."""
        return (self.appear(self.I_ACTIVITY_999_ELITE_PAGE)
                or self.appear(self.I_ACTIVITY_999_ECHO_HOME)
                or self.appear(self.I_ACTIVITY_999_HOME))

    def dismiss_activity_battle_result(self):
        """Dismiss reward panels and item detail popups without trusting template loss."""
        timer = Timer(self.PAGE_WAIT_TIMEOUT).start()
        while not timer.reached():
            self.screenshot()
            if self.is_activity_battle_result_closed():
                break
            self.click(self.C_ACTIVITY_999_BATTLE_WIN, interval=0.8)
            # This loop has its own deadline; do not let repeated safe clicks
            # trigger click protection before that deadline is evaluated.
            self.device.click_record_clear()
        else:
            raise RequestHumanTakeover('999 battle result could not be closed')
        self.dismiss_supply_popups()

    def dismiss_supply_popups(self):
        """关闭结算后弹出的灵符补给/金花灵符推荐窗。

        弹窗没有关闭按钮，点击画面最底部边缘（遮罩外区域）即可关闭；
        弹窗可能多层叠加，固定清理两轮。未弹出时该点击落在精锐页
        底部空白处，无副作用。
        """
        for _ in range(2):
            self.click(self.C_ACTIVITY_999_POPUP_GAP)
            time.sleep(1.0)

    @staticmethod
    def wait_after_activity_battle():
        delay = lognormal_delay(**BATTLE_SETTLEMENT_DELAY)
        logger.info(f'999 battle ended; wait {delay:.1f}s before returning to challenge page')
        time.sleep(delay)

    @staticmethod
    def wait_before_next_challenge():
        delay = lognormal_delay(**FIRST_OPERATION_DELAY)
        logger.info(f'Wait {delay:.1f}s before next 999 challenge')
        time.sleep(delay)

    def wait_or_raise(self, target, message, timeout=None):
        """Wait for a required page marker and fail with a useful reason."""
        timeout = timeout or self.PAGE_WAIT_TIMEOUT
        if not self.wait_until_appear(target, wait_time=timeout):
            raise RequestHumanTakeover(message)

    def wait_echo_map_or_battle(self):
        """点击战斗入口后等待回响地图出现。

        加载动画过长时地图锚点会晚到; 若期间检测到已进入准备页或战斗中,
        说明这次点击直接生效开打了, 返回 'battle' 交给调用方接战斗流程,
        避免把进行中的战斗留在现场后请求人工接管。
        """
        timer = Timer(self.BATTLE_MAP_TIMEOUT).start()
        while not timer.reached():
            self.screenshot()
            if self.appear(self.I_ACTIVITY_999_ECHO_HOME):
                return 'map'
            if self.is_in_prepare(False) or self.is_in_real_battle(False):
                logger.info('999 battle started before echo map appeared')
                return 'battle'
            time.sleep(0.5)
        raise RequestHumanTakeover('999 battle map did not appear')

    def open_elite_page_from_activity(self):
        """Move from the activity home/echo page to the elite challenge page."""
        self.screenshot()
        if self.appear(self.I_ACTIVITY_999_ELITE_PAGE):
            return

        if self.appear(self.I_ACTIVITY_999_HOME):
            logger.info('999 activity home detected')
            self.click(self.C_ACTIVITY_999_BATTLE)
            result = self.wait_echo_map_or_battle()
            if result == 'battle':
                # 点战斗直接开打了: 打完这场再回精锐页
                self.finish_battle()
                return
            self.screenshot()

        if not self.appear(self.I_ACTIVITY_999_ECHO_HOME):
            raise RequestHumanTakeover('999 activity page state is unknown')

        # 地图入场动画可能吞掉第一次点击，循环重试直到精锐页出现。
        timer = Timer(self.PAGE_WAIT_TIMEOUT).start()
        while not timer.reached():
            self.screenshot()
            if self.appear(self.I_ACTIVITY_999_ELITE_PAGE):
                return
            self.click(self.C_ACTIVITY_999_ELITE_MENU, interval=1.5)
            # 该循环有自己的超时兜底，重试点击不应在此之前触发点击保护。
            self.device.click_record_clear()
        raise RequestHumanTakeover('999 elite page did not appear')

    def _entry_visible(self) -> bool:
        """活动入口各庭院皮肤样式与位置不同, 任一已采集模板命中即可。"""
        return (self.appear(self.I_ACTIVITY_999_ENTRY)
                or self.appear(self.I_ACTIVITY_999_ENTRY_MAIN1))

    def enter_activity(self):
        """Enter the activity from courtyard and open the elite page."""
        self.screenshot()
        if not self._entry_visible():
            self.goto_page(page_main)
            self.screenshot()
        if not self._entry_visible():
            raise RequestHumanTakeover('999 activity entrance not found in courtyard')

        # 命中哪个模板就点哪个, 避免跨皮肤点击错误位置
        if self.appear(self.I_ACTIVITY_999_ENTRY):
            self.click(self.I_ACTIVITY_999_ENTRY)
        else:
            self.click(self.I_ACTIVITY_999_ENTRY_MAIN1)
        logger.info('Click 999 activity entrance')
        self.wait_or_raise(
            self.I_ACTIVITY_999_HOME,
            '999 activity home did not appear after clicking entrance',
        )
        self.open_elite_page_from_activity()

    def restore_elite_page(self):
        """Accept the possible landing pages after settlement and recover."""
        timer = Timer(self.PAGE_WAIT_TIMEOUT).start()
        while not timer.reached():
            self.screenshot()
            if self.appear(self.I_ACTIVITY_999_ELITE_PAGE):
                return
            if (self.appear(self.I_ACTIVITY_999_ECHO_HOME)
                    or self.appear(self.I_ACTIVITY_999_HOME)):
                logger.warning('999 settlement returned to an upper activity page; recovering')
                self.open_elite_page_from_activity()
                return
            time.sleep(0.4)
        raise RequestHumanTakeover('999 elite page did not return after battle settlement')

    def confirm_challenge_started(self) -> bool:
        """确认挑战点击生效；被残留弹窗吞掉时清理后重试。

        点击挑战后精锐页标题会在几秒内被加载/准备页替换；若持续停留在
        精锐页，说明点击被弹窗遮罩吞掉，此时点击面板缝隙关闭弹窗并重试。
        重试后购买引导窗仍弹出，说明挑战票已耗尽，返回 False 由调用方
        正常结束任务。

        Returns:
            True 表示战斗已开始；False 表示票已耗尽无法继续挑战。
        """
        for attempt in range(3):
            leave_timer = Timer(8).start()
            stayed = True
            while not leave_timer.reached():
                self.screenshot()
                if not self.appear(self.I_ACTIVITY_999_ELITE_PAGE):
                    stayed = False
                    break
                time.sleep(0.5)
            if not stayed:
                return True
            if attempt > 0:
                # 关闭弹窗后再次点击挑战仍弹出引导窗，判定为票已耗尽。
                logger.info('999 challenge tickets exhausted; activity finished')
                self.click(self.C_ACTIVITY_999_POPUP_GAP)
                time.sleep(1.0)
                return False
            logger.warning('999 challenge click did not start a battle; closing leftover popup and retrying')
            self.click(self.C_ACTIVITY_999_POPUP_GAP)
            time.sleep(1.0)
            self.screenshot()
            if not self.appear(self.I_ACTIVITY_999_CHALLENGE):
                raise RequestHumanTakeover('999 challenge button unavailable after popup cleanup')
            self.click(self.C_ACTIVITY_999_CHALLENGE)
        return False

    def finish_battle(self):
        """Run one battle and return to a usable elite challenge page."""
        result = self.run_general_battle(
            self.config.activity_999.general_battle_config)
        if not result:
            raise RequestHumanTakeover('999 elite battle failed')
        self.wait_after_activity_battle()
        self.restore_elite_page()

    def get_start_state(self):
        """Detect the current 999 state before making any navigation click."""
        if self.is_activity_battle_win():
            return 'settlement'
        if self.is_in_prepare(False) or self.is_in_real_battle(False):
            # A generic battle screen has no 999-specific marker. On a cold
            # start it is unsafe to assume that another task's battle belongs
            # to this activity.
            return 'battle_unknown'
        if self.appear(self.I_ACTIVITY_999_ELITE_PAGE):
            return 'elite'
        if self.appear(self.I_ACTIVITY_999_ECHO_HOME):
            return 'echo'
        if self.appear(self.I_ACTIVITY_999_HOME):
            return 'home'
        if self.appear(self.I_ACTIVITY_999_BACK):
            return 'activity_unknown'
        return 'outside'

    def recover_unknown_subpage(self) -> str:
        """在活动内但子页未知时, 点击左上角返回逐级退出并重新识别。

        游戏重启后常直接恢复到活动深层的某个界面, 状态机认不出具体子页;
        每次点返回后重新判定, 回到已知子页即返回该状态。
        """
        for _ in range(4):
            self.screenshot()
            state = self.get_start_state()
            if state != 'activity_unknown':
                return state
            logger.info('999 unknown subpage, clicking back to recover')
            self.click(self.C_ACTIVITY_999_BACK, interval=1.5)
            self.device.click_record_clear()
            time.sleep(1.0)
        return self.get_start_state()

    def run(self):
        logger.hr('999 ACTIVITY', level=1)
        self.screenshot()
        state = self.get_start_state()
        if state == 'activity_unknown':
            # 游戏重启后可能恢复在活动深层界面, 先点返回恢复到已知子页
            state = self.recover_unknown_subpage()
        logger.info(f'999 startup state: {state}')

        if state == 'settlement':
            self.dismiss_activity_battle_result()
            self.restore_elite_page()
            self.run_elite_loop()
            return
        if state == 'battle_unknown':
            raise RequestHumanTakeover(
                'Battle detected at 999 startup, but it cannot be verified as an activity battle')
        if state == 'elite':
            self.run_elite_loop()
            return
        if state in ('home', 'echo'):
            self.open_elite_page_from_activity()
        elif state == 'outside':
            self.enter_activity()
        else:
            # 恢复后仍是未知状态(返回链上出现了不认识的界面), 交给人工处理
            raise RequestHumanTakeover(
                '999 is inside the activity, but the current subpage is unknown')
        self.run_elite_loop()

    def run_elite_loop(self):
        """Repeat elite battles until resources run out or the page becomes abnormal."""
        battle_count_limit = (
            self.config.activity_999.activity_999_config.battle_count_limit
        )
        run_time_limit = self.config.activity_999.activity_999_config.run_time_limit
        run_time_limit_seconds = (
            run_time_limit.hour * 3600
            + run_time_limit.minute * 60
            + run_time_limit.second
        )
        started_at = time.monotonic()
        completed_count = 0
        logger.info(
            f'999 battle count limit: '
            f'{battle_count_limit if battle_count_limit > 0 else "unlimited"}'
        )
        logger.info(
            f'999 run time limit: '
            f'{run_time_limit if run_time_limit_seconds > 0 else "unlimited"}'
        )
        while True:
            if (
                run_time_limit_seconds > 0
                and time.monotonic() - started_at >= run_time_limit_seconds
            ):
                logger.info('999 run time limit reached, task finished')
                return
            self.screenshot()
            if not self.appear(self.I_ACTIVITY_999_ELITE_PAGE):
                raise RequestHumanTakeover('999 elite page not found before challenge')
            if not self.appear(self.I_ACTIVITY_999_CHALLENGE):
                raise RequestHumanTakeover('999 challenge button unavailable; resources may be exhausted')
            self.wait_before_next_challenge()
            # BOSS 展示页的粒子动画会瞬时拉低按钮匹配分，单帧误判率高；
            # 在 3 秒窗口内多帧确认，页面真变了才放弃。
            confirm_timer = Timer(3).start()
            page_ok = False
            while not confirm_timer.reached():
                self.screenshot()
                if (self.appear(self.I_ACTIVITY_999_ELITE_PAGE)
                        and self.appear(self.I_ACTIVITY_999_CHALLENGE)):
                    page_ok = True
                    break
                time.sleep(0.4)
            if not page_ok:
                raise RequestHumanTakeover('999 challenge page changed during random delay')
            self.click(self.C_ACTIVITY_999_CHALLENGE)
            logger.info('Click 999 elite challenge')
            if not self.confirm_challenge_started():
                # 挑战票耗尽，今日活动打完，按正常完成顺延下次运行。
                self.set_next_run(task='Activity999', success=True, finish=True)
                raise TaskEnd
            self.finish_battle()
            completed_count += 1
            logger.info(
                f'999 completed battles: {completed_count}'
                f'/{battle_count_limit if battle_count_limit > 0 else "unlimited"}'
            )
            if 0 < battle_count_limit <= completed_count:
                logger.info('999 battle count limit reached, task finished')
                return
            if (
                run_time_limit_seconds > 0
                and time.monotonic() - started_at >= run_time_limit_seconds
            ):
                logger.info('999 run time limit reached, task finished')
                return
