# This Python file uses the following encoding: utf-8
from datetime import datetime

from module.base.timer import Timer
from module.exception import TaskEnd
from module.logger import logger
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main
from tasks.Component.GeneralBattle.assets import GeneralBattleAssets
from tasks.OutingRitual.assets import OutingRitualAssets


class ScriptTask(GameUi, GeneralBattleAssets, OutingRitualAssets):
    def mark_battle_wait(self):
        """Use the framework's long wait watchdog while an auto battle is running."""
        self.device.stuck_record_clear()
        self.device.stuck_record_add('BATTLE_STATUS_S')
        self.device.click_record_clear()

    def enter_event(self):
        self.screenshot()
        if self.appear(self.I_OR_START):
            return True

        self.ui_get_current_page()
        self.ui_goto(page_main)
        timeout = Timer(40).start()
        while not timeout.reached():
            self.screenshot()
            if self.appear(self.I_OR_START):
                logger.info('Entered Outing Ritual board')
                return True
            if self.appear(self.I_OR_HUB_PAGE):
                if self.appear_then_click(self.I_OR_HUB_ENTRY, interval=2):
                    logger.info('Open Outing Ritual from event hub')
                    continue
            if self.appear_then_click(self.I_OR_COURTYARD_ENTRY, interval=2):
                logger.info('Open Yunhua event hub from courtyard')
                continue
        logger.warning('Unable to enter Outing Ritual from courtyard')
        return False

    def run(self):
        conf = self.config.model.outing_ritual.outing_ritual_config
        started_at = datetime.now()
        completed = 0
        turn_running = False
        saw_busy = False
        duel_handled = False
        stage_handled = False
        challenge_handled = False
        battle_waiting = False
        turn_timer = Timer(150).start()
        settle_timer = Timer(15).start()

        logger.hr('Outing Ritual', 1)
        logger.info('Entering Outing Ritual')
        if not self.enter_event():
            self.set_next_run(task='OutingRitual', success=False, finish=False)
            raise TaskEnd('OutingRitual entry failed')
        page_wait = Timer(20).start()

        while True:
            self.screenshot()
            if self.ui_reward_appear_click(False):
                continue
            if (not challenge_handled and
                    self.appear_then_click(self.I_OR_CHALLENGE, self.C_OR_CHALLENGE, interval=2)):
                challenge_handled = True
                saw_busy = True
                battle_waiting = True
                self.mark_battle_wait()
                logger.info('Start Outing Ritual challenge battle')
                continue
            if self.appear_then_click(self.I_PREPARE_HIGHLIGHT, interval=1):
                saw_busy = True
                battle_waiting = True
                self.mark_battle_wait()
                logger.info('Prepare Outing Ritual battle')
                continue
            if self.appear_then_click(self.I_WIN, self.C_WIN_1, interval=1):
                saw_busy = True
                battle_waiting = False
                logger.info('Confirm Outing Ritual battle victory')
                continue
            if self.appear_then_click(self.I_FALSE, self.C_WIN_1, interval=1):
                saw_busy = True
                battle_waiting = False
                logger.info('Confirm Outing Ritual battle result')
                continue
            if (self.appear_then_click(self.I_REWARD, self.C_REWARD_1, interval=1) or
                    self.appear_then_click(self.I_REWARD_GOLD, self.C_REWARD_1, interval=1)):
                saw_busy = True
                battle_waiting = False
                logger.info('Claim Outing Ritual battle reward')
                continue
            if (not duel_handled and
                    self.appear_then_click(self.I_OR_DUEL_THROW, self.C_OR_DUEL_THROW, interval=2)):
                duel_handled = True
                saw_busy = True
                logger.info('Throw dice in Outing Ritual duel')
                continue
            if (not stage_handled and
                    self.appear_then_click(self.I_OR_STAGE_SELECT, self.C_OR_STAGE_SELECT, interval=2)):
                stage_handled = True
                saw_busy = True
                logger.info('Select opponent stage in Outing Ritual')
                continue

            start_visible = self.appear(self.I_OR_START)
            on_board = start_visible or self.appear(self.I_OR_PAGE)
            if not on_board:
                if turn_running:
                    if not battle_waiting and turn_timer.reached():
                        logger.warning('Current Outing Ritual turn timed out')
                        break
                    continue
                if page_wait.reached():
                    logger.warning('Outing Ritual board was not found; open the event page before running this task')
                    break
                continue

            page_wait.reset()
            if turn_running and not start_visible:
                saw_busy = True

            if turn_running and start_visible and (saw_busy or settle_timer.reached()):
                completed += 1
                turn_running = False
                saw_busy = False
                duel_handled = False
                stage_handled = False
                challenge_handled = False
                battle_waiting = False
                logger.info(f'Outing Ritual turn completed: {completed}')
                if conf.run_count and completed >= conf.run_count:
                    logger.info('Configured run count reached')
                    break

            if turn_running and start_visible and not saw_busy:
                # The start button remains visible during the opening animation.
                # Never click it twice: repeated clicks queue additional turns.
                if turn_timer.reached():
                    logger.warning('A new turn did not start; activity attempts may be exhausted')
                    break
                continue

            if not start_visible:
                continue
            # Apply the task duration only between turns. A battle already in
            # progress must be allowed to finish, even when it runs for a long time.
            if datetime.now() - started_at >= conf.limit_time:
                logger.warning('Outing Ritual time limit reached on event board')
                break
            logger.info(f'Start Outing Ritual turn {completed + 1}')
            self.click(self.C_OR_START, interval=2)
            turn_running = True
            saw_busy = False
            duel_handled = False
            stage_handled = False
            challenge_handled = False
            battle_waiting = False
            turn_timer.reset()
            settle_timer.reset()

        self.set_next_run(task='OutingRitual', success=True, finish=True)
        raise TaskEnd('OutingRitual')
