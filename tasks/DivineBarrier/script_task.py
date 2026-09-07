# This Python file uses the following encoding: utf-8
from datetime import datetime

from module.base.timer import Timer
from module.exception import TaskEnd
from module.logger import logger
from tasks.Component.GeneralBattle.assets import GeneralBattleAssets
from tasks.DivineBarrier.assets import DivineBarrierAssets
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main
from tasks.OutingRitual.assets import OutingRitualAssets


class ScriptTask(GameUi, GeneralBattleAssets, OutingRitualAssets, DivineBarrierAssets):
    def mark_battle_wait(self):
        """Use the framework's long wait watchdog while an auto battle is running."""
        self.device.stuck_record_clear()
        self.device.stuck_record_add('BATTLE_STATUS_S')
        self.device.click_record_clear()

    def enter_event(self):
        self.screenshot()
        if self.appear(self.I_DB_CHALLENGE):
            return True
        self.ui_get_current_page()
        self.ui_goto(page_main)
        timeout = Timer(40).start()
        while not timeout.reached():
            self.screenshot()
            if self.appear(self.I_DB_CHALLENGE):
                logger.info('Entered Divine Barrier')
                return True
            if self.appear(self.I_OR_HUB_PAGE):
                if self.appear_then_click(self.I_DB_HUB_ENTRY, self.C_DB_HUB_ENTRY, interval=2):
                    logger.info('Open Divine Barrier from event hub')
                    continue
            if self.appear_then_click(self.I_OR_COURTYARD_ENTRY, interval=2):
                logger.info('Open Yunhua event hub from courtyard')
                continue
        return False

    def run(self):
        conf = self.config.model.divine_barrier.divine_barrier_config
        started_at = datetime.now()
        completed = 0
        battle_running = False
        battle_progress = False
        start_attempts = 0
        battle_timer = Timer(90).start()
        retry_timer = Timer(5).start()

        logger.hr('Divine Barrier', 1)
        if not self.enter_event():
            self.set_next_run(task='DivineBarrier', success=False, finish=False)
            raise TaskEnd('DivineBarrier entry failed')

        while True:
            self.screenshot()
            challenge_visible = self.appear(self.I_DB_CHALLENGE)

            if battle_running and challenge_visible and battle_progress:
                completed += 1
                battle_running = False
                battle_progress = False
                start_attempts = 0
                logger.info(f'Divine Barrier battle completed: {completed}')
                if conf.run_count and completed >= conf.run_count:
                    break

            if not battle_running and challenge_visible:
                # Never stop in preparation or battle. Check the task time
                # limit only after the previous result has returned here.
                if datetime.now() - started_at >= conf.limit_time:
                    logger.warning('Divine Barrier time limit reached on challenge page')
                    break
                logger.info(f'Start Divine Barrier battle {completed + 1}')
                self.click(self.C_DB_CHALLENGE, interval=2)
                battle_running = True
                start_attempts = 1
                self.mark_battle_wait()
                battle_timer.reset()
                retry_timer.reset()
                continue

            if battle_running and challenge_visible and not battle_progress and retry_timer.reached():
                if start_attempts >= 3:
                    logger.warning('Divine Barrier challenge button did not respond; resources may be insufficient')
                    break
                start_attempts += 1
                logger.info(f'Retry Divine Barrier challenge ({start_attempts}/3)')
                self.click(self.C_DB_CHALLENGE)
                retry_timer.reset()
                continue

            if self.appear_then_click(self.I_PREPARE_HIGHLIGHT, interval=1):
                battle_progress = True
                self.mark_battle_wait()
                logger.info('Prepare Divine Barrier battle')
                continue
            if self.appear_then_click(self.I_WIN, self.C_WIN_1, interval=1):
                battle_progress = True
                logger.info('Confirm Divine Barrier victory')
                continue
            if self.appear_then_click(self.I_FALSE, self.C_WIN_1, interval=1):
                battle_progress = True
                logger.info('Confirm Divine Barrier result')
                continue
            if (self.appear_then_click(self.I_REWARD, self.C_REWARD_1, interval=1) or
                    self.appear_then_click(self.I_REWARD_GOLD, self.C_REWARD_1, interval=1)):
                battle_progress = True
                logger.info('Claim Divine Barrier reward')
                continue
            if battle_running and not battle_progress and battle_timer.reached():
                logger.warning('Divine Barrier did not start or timed out; resources may be insufficient')
                break
        self.set_next_run(task='DivineBarrier', success=True, finish=True)
        raise TaskEnd('DivineBarrier')
