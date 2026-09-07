import time

from module.base.timer import Timer
from module.exception import RequestHumanTakeover
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
                return
            self.click(self.C_ACTIVITY_999_BATTLE_WIN, interval=0.8)
            # This loop has its own deadline; do not let repeated safe clicks
            # trigger click protection before that deadline is evaluated.
            self.device.click_record_clear()
        raise RequestHumanTakeover('999 battle result could not be closed')

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

    def open_elite_page_from_activity(self):
        """Move from the activity home/echo page to the elite challenge page."""
        self.screenshot()
        if self.appear(self.I_ACTIVITY_999_ELITE_PAGE):
            return

        if self.appear(self.I_ACTIVITY_999_HOME):
            logger.info('999 activity home detected')
            self.click(self.C_ACTIVITY_999_BATTLE)
            self.wait_or_raise(
                self.I_ACTIVITY_999_ECHO_HOME,
                '999 battle map did not appear',
            )
            self.screenshot()

        if not self.appear(self.I_ACTIVITY_999_ECHO_HOME):
            raise RequestHumanTakeover('999 activity page state is unknown')

        self.click(self.C_ACTIVITY_999_ELITE_MENU)
        self.wait_or_raise(
            self.I_ACTIVITY_999_ELITE_PAGE,
            '999 elite page did not appear',
        )

    def enter_activity(self):
        """Enter the activity from courtyard and open the elite page."""
        self.screenshot()
        if not self.appear(self.I_ACTIVITY_999_ENTRY):
            self.ui_get_current_page()
            self.ui_goto(page_main)
            self.screenshot()
        if not self.appear(self.I_ACTIVITY_999_ENTRY):
            raise RequestHumanTakeover('999 activity entrance not found in courtyard')

        self.click(self.I_ACTIVITY_999_ENTRY)
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

    def run(self):
        logger.hr('999 ACTIVITY', level=1)
        self.screenshot()
        state = self.get_start_state()
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
            # Keep the user inside the activity instead of letting generic UI
            # navigation press Back until it reaches the courtyard.
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
            self.screenshot()
            if not (self.appear(self.I_ACTIVITY_999_ELITE_PAGE)
                    and self.appear(self.I_ACTIVITY_999_CHALLENGE)):
                raise RequestHumanTakeover('999 challenge page changed during random delay')
            self.click(self.C_ACTIVITY_999_CHALLENGE)
            logger.info('Click 999 elite challenge')
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
