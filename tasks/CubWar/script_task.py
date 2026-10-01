# This Python file uses the following encoding: utf-8
from datetime import datetime

from module.exception import TaskEnd
from module.logger import logger
from module.base.timer import Timer
from module.atom.click import RuleClick

from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main, page_shikigami_records
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.CubWar.assets import CubWarAssets
from tasks.CubWar.config import CubWar


class ScriptTask(GameUi, GeneralBattle, SwitchSoul, CubWarAssets):

    def run(self):
        """
        为崽而战·八百八狸盛宴退治主流程（限时活动，boss 每天 14:00 开启）
        """
        cfg: CubWar = self.config.cub_war
        logger.hr('为崽而战·八百八狸盛宴', 2)
        # 进活动前先切御魂
        if cfg.switch_soul_config.enable:
            self.goto_page(page_shikigami_records)
            self.run_switch_soul(cfg.switch_soul_config.switch_group_team)
        if cfg.switch_soul_config.enable_switch_by_name:
            self.goto_page(page_shikigami_records)
            self.run_switch_soul_by_name(cfg.switch_soul_config.group_name, cfg.switch_soul_config.team_name)

        if not self.goto_cub_war():
            logger.warning("[崽战退治] 未能进入八百八狸盛宴，可能活动未开放、未到 14 点或已结束")
            self.goto_page(page_main)
            self.set_next_run(task='CubWar', success=False, finish=True)
            raise TaskEnd

        success = self.cub_war_battle(cfg)

        # 逐级返回庭院再回主界面
        self.exit_cub_war()
        self.goto_page(page_main)
        self.set_next_run(task='CubWar', success=success, finish=True)
        raise TaskEnd

    def goto_cub_war(self) -> bool:
        """
        庭院 → 为崽而战主页 → 八百八狸盛宴地图 → 首领战斗挑战页
        途中处理三个活动弹窗：讨伐开启（立即前往）、本寮分组（点空白关闭）、活动规则（点✕）
        """
        self.goto_page(page_main)
        timer = Timer(90).start()
        while not timer.reached():
            self.screenshot()
            # 已到挑战页
            if self.appear(self.I_CHECK_CHALLENGE):
                logger.info("[崽战退治] 已进入首领战斗挑战页")
                return True
            # 活动弹窗优先处理
            if self.cub_war_close_popup():
                continue
            # 盛宴地图：点击讨伐中的八百八狸
            if self.appear(self.I_CHECK_FEAST_MAP):
                if self.appear_then_click(self.I_GOTO_BOSS, interval=1.5):
                    continue
            # 活动主页：点击八百八狸盛宴横幅
            if self.appear(self.I_CHECK_CUB_WAR_PAGE):
                if self.appear_then_click(self.I_GOTO_FEAST, interval=1.5):
                    continue
            # 庭院：点击右侧为崽而战入口
            if self.appear_then_click(self.I_MAIN_GOTO_CUB_WAR, interval=2):
                continue
        logger.warning("[崽战退治] 进入八百八狸盛宴超时")
        return False

    def cub_war_close_popup(self) -> bool:
        """
        关闭崽战活动内的弹窗：讨伐开启、本寮分组、活动规则
        Returns:
            bool: 本轮截图命中并处理了任一弹窗
        """
        # 讨伐开启弹窗：点立即前往（跳向首领）
        if self.appear_then_click(self.I_GOTO_PUSH, interval=2):
            logger.info("[崽战退治] 讨伐开启弹窗，点击立即前往")
            return True
        # 活动规则等弹窗：点右上角✕
        if self.appear_then_click(self.I_POPUP_CLOSE, interval=2):
            logger.info("[崽战退治] 关闭活动弹窗")
            return True
        # 本寮分组弹窗：提示点击空白处关闭
        if self.appear(self.I_CHECK_GROUP):
            self.click(RuleClick(roi_front=(600, 590, 80, 40), roi_back=(600, 590, 80, 40),
                                 name='CUB_WAR_BLANK_CLICK'), interval=1.5)
            logger.info("[崽战退治] 点击空白处关闭本寮分组弹窗")
            return True
        return False

    def cub_war_battle(self, cfg: CubWar) -> bool:
        """
        挑战页连打循环。

        boss 战限时 3 分钟，打满时间按伤害结算并发奖；队伍被团灭会提前结束。
        团灭视为打不过，停止连打；否则在每日消耗上限内继续挑战。
        """
        battle_count = 0
        ocr_fail = 0
        idle = 0
        while 1:
            self.screenshot()
            if not self.appear(self.I_CHECK_CHALLENGE):
                logger.warning("[崽战退治] 当前不在挑战页，停止连打")
                break
            if battle_count >= 20:
                logger.warning("[崽战退治] 单次运行已达 20 场上限，收工")
                break
            # 每日消耗上限（已用/剩余/总量）
            used, remain, total = self.O_DAILY_LIMIT.ocr(self.device.image)
            if total > 0:
                ocr_fail = 0
                if remain <= 0:
                    logger.info(f"[崽战退治] 今日消耗已达上限 {used}/{total}，收工")
                    break
            else:
                ocr_fail += 1
                if ocr_fail >= 3 and battle_count >= 1:
                    logger.warning("[崽战退治] 每日消耗上限连续识别失败，保守收工")
                    break
            # 点击退治进入战斗
            if not self.appear_then_click(self.I_RETREAT_FIRE, interval=2):
                idle += 1
                if idle >= 8:
                    logger.warning("[崽战退治] 退治按钮长时间不可点击，停止连打")
                    break
                continue
            idle = 0
            # 等待离开挑战页（战斗加载），避免通用战斗把挑战页误判为战斗结束页
            left = False
            page_timer = Timer(15).start()
            while not page_timer.reached():
                self.screenshot()
                if not self.appear(self.I_CHECK_CHALLENGE):
                    left = True
                    break
            if not left:
                logger.warning("[崽战退治] 点击退治后未进入战斗，重试")
                continue
            battle_count += 1
            started = datetime.now()
            self.run_general_battle(
                config=cfg.general_battle,
                exit_matcher=self.I_CHECK_CHALLENGE,
            )
            cost = (datetime.now() - started).total_seconds()
            # boss 战限时 3 分钟：打满约 3 分钟为正常结算；数十秒内返回即被团灭
            if cost < 60:
                logger.warning(f"[崽战退治] 第 {battle_count} 场仅 {cost:.0f} 秒结束，判定被团灭，停止连打")
                break
            logger.info(f"[崽战退治] 第 {battle_count} 场打完，耗时 {cost:.0f} 秒")
        return battle_count > 0

    def exit_cub_war(self) -> None:
        """
        从崽战活动内逐级返回庭院（挑战页/盛宴地图/活动主页共用左上角返回位）
        """
        timer = Timer(60).start()
        while not timer.reached():
            self.screenshot()
            if self.appear(self.I_CHECK_MAIN):
                logger.info("[崽战退治] 已返回庭院")
                return
            if (self.appear(self.I_CHECK_CHALLENGE) or self.appear(self.I_CHECK_FEAST_MAP)
                    or self.appear(self.I_CHECK_CUB_WAR_PAGE)):
                self.click(RuleClick(roi_front=(14, 8, 44, 44), roi_back=(14, 8, 44, 44),
                                     name='CUB_WAR_PAGE_BACK'), interval=1.5)
        logger.warning("[崽战退治] 返回庭院超时")


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)
    t.screenshot()

    t.run()
