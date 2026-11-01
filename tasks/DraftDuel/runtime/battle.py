"""协同对弈：战斗标志防抖与结算。"""
import time
from module.logger import logger
from tasks.GameUi.default_pages import random_click
from tasks.Component.GeneralBattle.assets import GeneralBattleAssets


class DraftDuelBattleMixin:
    BATTLE_END_ABSENCE = 2.0

    def _confirm_small_game_end(self):
        if getattr(self, '_draft_end_recorded', False):
            return
        self.device.click_record_clear()
        self.draft_finished_small_games = getattr(self, 'draft_finished_small_games', 0) + 1
        self._draft_round_had_battle = True
        self._record_small_game_stats()
        self._draft_end_recorded = True
        self._save_draft_checkpoint('settlement')
        logger.info(f'[协同对弈] 小局结束，已完成 {self.draft_finished_small_games} 局')

    def _clear_final_banner(self, wait=12.0, timeout=30.0, max_clicks=3):
        """清除与大厅同屏的大轮最终结算横幅。

        该横幅只挡大厅中部，大厅标志 I_WAIT_FIGHT_LOBBY 仍露在外面，若直接判定回大厅
        会在结算未完成时推进新大轮。故先等过场自行消失，超时后点顶部空白条推进，
        点击严格限次（避免狂点触发 GameTooManyClickError）。
        """
        start = time.monotonic()
        deadline = start + timeout
        clicks, last = 0, 0.0
        while True:
            if not self.appear(self.I_DRAFT_FINAL_BANNER):
                return True
            now = time.monotonic()
            # 顶部空白条为安全区：本页左右是与大厅同屏的规则面板/排名按钮，底部是功能按钮
            if now - start >= wait and clicks < max_clicks and now - last >= 3.0:
                self.click(random_click(ltrb=(False, True, False, False)))
                clicks += 1
                last = now
            if now >= deadline:
                logger.warning('[协同对弈] 最终结算横幅清除超时')
                return False
            self.device.stuck_record_clear()
            self.screenshot()
            time.sleep(1)

    def _clear_reward_page(self, timeout=30.0, max_clicks=3, interval=2.0):
        """清除奖励展示页：点底部「点击屏幕继续」文字带推进。

        该页与大厅同屏，大厅标志仍可见，必须先清掉再判定回大厅，
        否则会误判「已回大厅」而在结算未完成时推进新大轮。
        只点文字笔画带（y≈686-704）；点文字上方散点会被吸收、页面不推进。
        点击严格限次，避免狂点触发 GameTooManyClickError。
        """
        start = time.monotonic()
        deadline = start + timeout
        clicks, last = 0, 0.0
        while True:
            if not self.appear(self.I_DRAFT_REWARD_POUCH):
                return True
            now = time.monotonic()
            if clicks < max_clicks and now - last >= interval:
                self.click(GeneralBattleAssets.C_BATTLE_STATE_CONTINUE, interval=1.5)
                clicks += 1
                last = now
            if now >= deadline:
                logger.warning('[协同对弈] 奖励展示页清除超时')
                return False
            self.device.stuck_record_clear()
            self.screenshot()
            time.sleep(1)

    def _battle_and_settlement(self):
        """标志持续消失才等待结算；真实结算页面确认结束，重现则恢复战斗。"""
        seen = getattr(self, '_draft_battle_seen', False)
        settling = getattr(self, '_draft_resume_phase', '') == 'settlement'
        absent_since, absent = None, 0
        battle_clicks_reset = False
        deadline = time.monotonic() + (120 if settling else self.SMALL_GAME_BATTLE_WINDOW)
        while True:
            self.device.stuck_record_clear()
            self.screenshot()
            now = time.monotonic()
            if self.appear(self._battle_info_rule()):
                # 上阵阶段可能已设置 seen；仍在本阶段首次见到战斗时清除跨局点击。
                if not battle_clicks_reset:
                    self.device.click_record_clear()
                    battle_clicks_reset = True
                if not seen or settling:
                    deadline = now + self.SMALL_GAME_BATTLE_WINDOW
                    logger.info('[协同对弈] 已进入或恢复小局战斗，等待窗口 300 秒')
                elif now >= deadline:
                    deadline = now + self.SMALL_GAME_BATTLE_WINDOW
                    logger.info('[协同对弈] 300 秒仍在战斗，等待再延 300 秒')
                self._sync_draft_state()
                self._draft_round_had_battle = True
                self._draft_battle_seen = True
                seen, settling = True, False
                absent_since, absent = None, 0
                self._save_draft_checkpoint('battle')
            else:
                if seen and not settling:
                    absent_since = now if absent_since is None else absent_since
                    absent += 1
                    if absent >= 2 and now - absent_since >= self.BATTLE_END_ABSENCE:
                        settling = True
                        deadline = now + 120
                        self._save_draft_checkpoint('settlement')
                if settling:
                    pages = (self.I_DRAFT_SHARE, self.I_FIGHT_STATISTIC, self.I_FIGHT_RESULT)
                    if any(self.appear(rule) for rule in pages):
                        self._confirm_small_game_end()
                        self.click(random_click(ltrb=(True, False, True, False)))
                    elif self.appear(self.I_WAIT_FIGHT_LOBBY):
                        # 大轮最终结算横幅与大厅同屏时大厅标志同样可见，必须先清除横幅，
                        # 否则会误判「已回大厅」而在结算未完成时推进新大轮
                        if self.appear(self.I_DRAFT_FINAL_BANNER):
                            if not self._clear_final_banner():
                                logger.warning('[协同对弈] 最终结算横幅未清除')
                                return None
                            continue
                        # 横幅之后会接着弹出奖励展示页，同样与大厅同屏，需点掉再判回大厅
                        if self.appear(self.I_DRAFT_REWARD_POUCH):
                            if not self._clear_reward_page():
                                logger.warning('[协同对弈] 奖励展示页未清除')
                                return None
                            continue
                        self._confirm_small_game_end()
                        self._observe_duel_lobby()
                        return 'lobby'
                    elif self.appear(self.I_POST_DRAFT_RANK):
                        self._confirm_small_game_end()
                        self._observe_victory_count()
                        self._save_draft_checkpoint('rank')
                        return 'rank'
                if now >= deadline and (settling or not seen):
                    logger.warning('[协同对弈] 战斗或结算无确认进展')
                    return None
            time.sleep(0.3)
