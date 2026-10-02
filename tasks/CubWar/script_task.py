# This Python file uses the following encoding: utf-8
from datetime import datetime

from module.exception import TaskEnd
from module.logger import logger
from module.base.timer import Timer
from module.atom.click import RuleClick

from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main, page_shikigami_records, page_battle, page_battle_prepare
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.CubWar.assets import CubWarAssets
from tasks.CubWar.config import CubWar, CubWarGroup

GROUP_NAMES = {
    CubWarGroup.Whale: '鲸组',
    CubWarGroup.Gull: '鸥组',
    CubWarGroup.Shark: '鲨组',
}


class ScriptTask(GameUi, GeneralBattle, SwitchSoul, CubWarAssets):

    def run(self):
        """
        为崽而战·八百八狸盛宴退治主流程（限时活动）
        首领开启时间以游戏内倒计时为准（且需所在分组占领相邻区域）；神社区域/妖怪退治按所在分组解锁情况开放
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

        if not self.goto_feast_map():
            logger.warning("[崽战退治] 未能进入八百八狸盛宴，可能活动未开放或已结束")
            self.goto_page(page_main)
            self.set_next_run(task='CubWar', success=False, finish=True)
            raise TaskEnd

        success = False
        settings = cfg.cub_war_settings
        self._cub_war_limit_reached = False
        # 首领·八百八狸（每场消耗 18 点）
        if settings.battle_boss:
            success = self.cub_war_boss_phase(cfg) or success
        # 神社区域（每场消耗 12 点）
        if settings.battle_shrine and not self._cub_war_limit_reached:
            success = self.cub_war_area_phase(cfg, shrine=True) or success
        # 已达每日消耗上限：妖怪退治必也打满，直接收工不再进入妖怪阶段
        if self._cub_war_limit_reached:
            logger.info("[崽战退治] 已达每日消耗上限，跳过妖怪退治阶段")
        elif settings.battle_yokai:
            success = self.cub_war_area_phase(cfg, shrine=False) or success

        # 逐级返回庭院再回主界面
        self.exit_cub_war()
        self.goto_page(page_main)
        self.set_next_run(task='CubWar', success=success, finish=True)
        raise TaskEnd

    def goto_feast_map(self) -> bool:
        """
        庭院 → 为崽而战主页 → 八百八狸盛宴地图
        途中处理三个活动弹窗：讨伐开启（立即前往）、本寮分组（点空白关闭）、活动规则（点✕）
        讨伐开启弹窗的「立即前往」可能直接跳进首领挑战页，同样视为进场成功
        """
        self.goto_page(page_main)
        timer = Timer(90).start()
        while not timer.reached():
            self.screenshot()
            # 已到盛宴地图
            if self.appear(self.I_CHECK_FEAST_MAP):
                logger.info("[崽战退治] 已进入八百八狸盛宴地图")
                return True
            # 讨伐开启弹窗直接跳到了首领挑战页
            if self.appear(self.I_CHECK_CHALLENGE):
                logger.info("[崽战退治] 讨伐开启弹窗已直接跳转首领挑战页")
                return True
            # 活动弹窗优先处理
            if self.cub_war_close_popup():
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

    def cub_war_boss_phase(self, cfg: CubWar) -> bool:
        """
        首领阶段：在盛宴地图找到「讨伐中」横幅进入挑战页连打。
        横幅只在讨伐开启后出现，未开启时稍候片刻即跳过。
        """
        self.screenshot()
        # 讨伐开启弹窗可能已直接跳到挑战页
        if self.appear(self.I_CHECK_CHALLENGE):
            return self.cub_war_battle(cfg)
        timer = Timer(12).start()
        while not timer.reached():
            self.screenshot()
            if self.appear(self.I_CHECK_CHALLENGE):
                return self.cub_war_battle(cfg)
            if not self.appear(self.I_CHECK_FEAST_MAP) and not self.back_to_feast_map():
                return False
            if self.cub_war_close_popup():
                continue
            if self.appear_then_click(self.I_GOTO_BOSS, interval=1.5):
                continue
        logger.info("[崽战退治] 地图上未找到讨伐中的八百八狸，可能未到开启时间，跳过首领")
        return False

    def cub_war_area_phase(self, cfg: CubWar, shrine: bool) -> bool:
        """
        区域退治阶段：在盛宴地图上寻找目标进入区域详情页连打。
        神社区域点鸟居进入；妖怪退治点驻扎的军队进入（发金光的格子为正在攻打的区域）。
        区域未解锁（无退治按钮）自动跳过；滑动地图有次数上限，找不到目标即结束该阶段。
        """
        label = '神社区域' if shrine else '妖怪退治'
        tag = '崽战神社' if shrine else '崽战妖怪'
        # 先点右下角指南针回到本组大部队所在位置，否则默认相机可能在别处，看到的格子都不是本组能攻打的
        self.cub_war_click_compass()
        if shrine:
            targets = [self.I_MAP_TORII]
        else:
            # 只有发金光且本组颜色小人驻扎的格子才能攻打：从奖券排名识别本组后按组选军队模板；
            # 三人军队为进攻主力（点击可进区域页），单兵多为行军队伍点开无反应，排后面兜底
            group = self.cub_war_detect_group()
            if group is None:
                logger.warning(f"[{tag}] 未能从奖券排名面板识别所在分组（本大人），跳过{label}")
                return False
            group_targets = {
                CubWarGroup.Whale: [self.I_MAP_ARMY_BLUE3, self.I_MAP_ARMY_BLUE1],
                CubWarGroup.Gull: [self.I_MAP_ARMY_YELLOW3, self.I_MAP_ARMY_YELLOW1],
                CubWarGroup.Shark: [self.I_MAP_ARMY_RED3, self.I_MAP_ARMY_RED1],
            }
            targets = group_targets[group]
            logger.info(f"[{tag}] 所在分组: {GROUP_NAMES[group]}")
        success = False
        attempts = 0
        swipes = 0
        # 记录点击后未能进入预期区域页的目标，避免反复点同一个「点不进去」的格子
        # 形成「点目标→未进入→返回地图→滑动→再点同一目标」的死循环触发反卡死守卫
        failed = set()
        while attempts < 4 and swipes < 4:
            self.screenshot()
            if self._cub_war_limit_reached:
                logger.info(f"[{tag}] 已达每日消耗上限，停止{label}阶段")
                break
            if self.cub_war_close_popup():
                continue
            if not self.appear(self.I_CHECK_FEAST_MAP):
                if not self.back_to_feast_map():
                    break
                continue
            # 优先找尚未失败过的目标，已确认点不进去的格子直接跳过
            hit = None
            for target in targets:
                if target in failed:
                    continue
                if self.appear(target):
                    hit = target
                    break
            if hit is None:
                if len(failed) >= len(targets):
                    logger.warning(f"[{tag}] 本组可攻打目标均已尝试但未能进入{label}，停止阶段")
                    break
                swipes += 1
                logger.info(f"[{tag}] 地图上暂未找到{label}目标，滑动地图继续找（{swipes}/4）")
                if swipes % 2 == 1:
                    self.device.swipe((920, 380), (430, 400), duration=(0.3, 0.5), control_name='CUB_WAR_MAP_DRAG')
                else:
                    self.device.swipe((430, 380), (920, 400), duration=(0.3, 0.5), control_name='CUB_WAR_MAP_DRAG')
                # 等地图滚动停稳再重新识别，避免滑动态误判为无目标
                settle = Timer(1.2).start()
                while not settle.reached():
                    self.screenshot()
                continue
            if not self.appear_then_click(hit, interval=1.5):
                continue
            entered = self.cub_war_wait_area_enter(shrine)
            if entered == 'battle':
                # 点军队多数情况直接开战：立即接管本场，结算后回地图继续找
                logger.info(f"[{tag}] 点击军队直接进入战斗，接管本场")
                win = self.run_general_battle(
                    config=cfg.general_battle,
                    exit_matcher=lambda: (self.appear(self.I_CHECK_FEAST_MAP) or self.appear(self.I_CHECK_SHRINE)
                                          or self.appear(self.I_CHECK_YOKAI)),
                )
                success = success or win
                if not win:
                    logger.warning(f"[{tag}] 接管的战斗战败，停止{label}阶段")
                    break
                attempts += 1
                if not self.back_to_feast_map():
                    break
                continue
            if entered == 'page':
                fought = self.cub_war_area_battle(cfg, shrine)
                success = success or fought
                attempts += 1
                if not fought:
                    # 进了区域页但没打成（区域未解锁/已达上限/无退治按钮）：该目标无需再进，
                    # 加入 failed 避免反复点同一鸟居或军队又退回；神社仅一个目标则直接结束本阶段
                    failed.add(hit)
                if not self.back_to_feast_map():
                    break
                if self._cub_war_limit_reached:
                    logger.info(f"[{tag}] 已达每日消耗上限，停止{label}阶段")
                    break
                continue
            # entered 为 '' 或 'other'：点击未进入预期区域页
            attempts += 1
            logger.warning(f"[{tag}] 点击目标后未进入{label}页（第 {attempts}/4 次）")
            failed.add(hit)
            # 若误入其它区域页，先退回盛宴地图再继续找其它目标
            if not self.appear(self.I_CHECK_FEAST_MAP):
                if not self.back_to_feast_map():
                    break
            continue
        logger.info(f"[{tag}] {label}阶段结束")
        return success

    def cub_war_click_compass(self) -> None:
        """
        点击盛宴地图右下角指南针，回到本组大部队所在位置。
        地图很大且默认相机未必在本组区域，不点指南针会看到别组的格子（神社未解锁、军队非本组色）。
        """
        timer = Timer(8).start()
        while not timer.reached():
            self.screenshot()
            if not self.appear(self.I_CHECK_FEAST_MAP):
                if not self.back_to_feast_map():
                    return
                continue
            if self.cub_war_close_popup():
                continue
            if self.appear_then_click(self.I_MAP_COMPASS, interval=2):
                # 等地图平移到位再继续识别
                settle = Timer(1.5).start()
                while not settle.reached():
                    self.screenshot()
                logger.info("[崽战退治] 点击指南针回到本组大部队所在位置")
                return
        logger.warning("[崽战退治] 未找到地图指南针")

    def cub_war_detect_group(self) -> CubWarGroup | None:
        """
        从左上角奖券排名面板识别本组：本大人印章所在行的组图标即本组。
        需在盛宴地图上调用（面板常驻左上角），识别失败返回 None。
        """
        for _ in range(3):
            self.screenshot()
            if not self.appear(self.I_CHECK_FEAST_MAP):
                if not self.back_to_feast_map():
                    return None
                continue
            if self.cub_war_close_popup():
                continue
            if not self.appear(self.I_GROUP_STAMP):
                continue
            _, stamp_y = self.I_GROUP_STAMP.coord()
            for group, icon in [
                (CubWarGroup.Whale, self.I_GROUP_WHALE),
                (CubWarGroup.Gull, self.I_GROUP_GULL),
                (CubWarGroup.Shark, self.I_GROUP_SHARK),
            ]:
                if not self.appear(icon):
                    continue
                _, icon_y = icon.coord()
                # 印章与组图标在同一行（行高约 45px）
                if abs(icon_y - stamp_y) <= 22:
                    logger.info(f"[崽战退治] 奖券排名识别所在分组: {GROUP_NAMES[group]}")
                    return group
        return None

    def cub_war_wait_area_enter(self, shrine: bool) -> str:
        """
        点击地图目标后等待进入结果。
        点军队多数情况直接开战，也可能进区域详情页；点鸟居进神社区域页。
        Returns:
            str: 'page' 进入预期区域页；'battle' 直接进入战斗；'other' 进入另一类区域页；'' 等待超时
        """
        page_check = self.I_CHECK_SHRINE if shrine else self.I_CHECK_YOKAI
        other_check = self.I_CHECK_YOKAI if shrine else self.I_CHECK_SHRINE
        timer = Timer(15).start()
        while not timer.reached():
            self.screenshot()
            if self.appear(page_check):
                self._cub_war_settle()
                return 'page'
            if self.appear(other_check):
                self._cub_war_settle()
                return 'other'
            if self.detect_page_in(page_battle_prepare, page_battle, include_global=False) is not None:
                self._cub_war_settle()
                return 'battle'
        return ''

    def _cub_war_settle(self, seconds: float = 1.5) -> None:
        """进入区域页/战斗页后等待画面稳定，期间持续刷新截图帧"""
        settle = Timer(seconds).start()
        while not settle.reached():
            self.screenshot()

    def cub_war_area_battle(self, cfg: CubWar, shrine: bool) -> bool:
        """
        区域详情页连打循环：按每日消耗上限与按钮 ×N 单次消耗控制次数。
        神社区域每场消耗 12 点、妖怪退治每场 6 点，消耗值实时读按钮角标。
        区域未解锁时无退治按钮，直接跳过；战败一次即停止该区域连打。
        """
        label = '神社区域' if shrine else '妖怪退治'
        tag = '崽战神社' if shrine else '崽战妖怪'
        page_check = self.I_CHECK_SHRINE if shrine else self.I_CHECK_YOKAI
        battle_count = 0
        ocr_fail = 0
        idle = 0
        while 1:
            self.screenshot()
            if not self.appear(page_check):
                logger.warning(f"[{tag}] 当前不在{label}页，停止连打")
                break
            if battle_count >= 20:
                logger.warning(f"[{tag}] 单次运行已达 20 场上限，收工")
                break
            # 每日消耗上限（已用/剩余/总量）与单次消耗（按钮 ×N）
            used, remain, total = self.O_DAILY_LIMIT.ocr(self.device.image)
            cost = self.O_RETREAT_COST.ocr(self.device.image)
            if total > 400 or used > total:
                # 页面刚加载时计数器可能粘连误解析（如 300 读成 3001），按识别失败处理
                used, remain, total = 0, 0, 0
            if total > 0:
                ocr_fail = 0
                if remain <= 0:
                    logger.info(f"[{tag}] 今日消耗已达上限 {used}/{total}，收工")
                    self._cub_war_limit_reached = True
                    break
                if cost > 0 and remain < cost:
                    logger.info(f"[{tag}] 剩余 {remain} 不足一次消耗 {cost}，收工")
                    self._cub_war_limit_reached = True
                    break
            else:
                ocr_fail += 1
                if ocr_fail >= 3 and battle_count >= 1:
                    logger.warning(f"[{tag}] 每日消耗上限连续识别失败，保守收工")
                    break
            # 无退治按钮：区域未解锁（需所在分组占领相邻区域）或刚被占领，再截一帧防渲染误判
            if not self.appear(self.I_RETREAT_FIRE):
                timer = Timer(2).start()
                while not timer.reached():
                    self.screenshot()
                    if self.appear(self.I_RETREAT_FIRE):
                        break
                if not self.appear(self.I_RETREAT_FIRE):
                    if battle_count == 0:
                        logger.info(f"[{tag}] {label}未开启退治（需所在分组占领相邻区域），跳过")
                    else:
                        logger.info(f"[{tag}] 退治按钮已消失（区域可能已被占领），停止连打")
                    break
            if not self.appear_then_click(self.I_RETREAT_FIRE, interval=2):
                idle += 1
                if idle >= 8:
                    logger.warning(f"[{tag}] 退治按钮长时间不可点击，停止连打")
                    break
                continue
            idle = 0
            # 等待离开区域页（战斗加载），避免通用战斗把区域页误判为战斗结束页
            left = False
            page_timer = Timer(15).start()
            while not page_timer.reached():
                self.screenshot()
                if not self.appear(page_check):
                    left = True
                    break
            if not left:
                logger.warning(f"[{tag}] 点击退治后未进入战斗，重试")
                continue
            battle_count += 1
            started = datetime.now()
            win = self.run_general_battle(
                config=cfg.general_battle,
                exit_matcher=page_check,
            )
            cost_seconds = (datetime.now() - started).total_seconds()
            if not win:
                logger.warning(f"[{tag}] 第 {battle_count} 场战败（耗时 {cost_seconds:.0f} 秒），停止{label}连打")
                break
            logger.info(f"[{tag}] 第 {battle_count} 场打完，耗时 {cost_seconds:.0f} 秒")
        return battle_count > 0

    def cub_war_battle(self, cfg: CubWar) -> bool:
        """
        首领挑战页连打循环。

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
            # 首领未开启：退治按钮带锁链，右下角显示开启倒计时与占领条件
            if self.appear(self.I_BOSS_LOCKED):
                countdown = self.O_BOSS_LOCKED_COUNTDOWN.ocr(self.device.image)
                if countdown:
                    logger.info(f"[崽战退治] 首领退治未开启（{countdown}，且需所在分组占领相邻区域），跳过")
                else:
                    logger.info("[崽战退治] 首领退治未开启（退治按钮带锁链），跳过")
                break
            # 每日消耗上限（已用/剩余/总量）与单次消耗（按钮 ×N）
            used, remain, total = self.O_DAILY_LIMIT.ocr(self.device.image)
            cost = self.O_RETREAT_COST.ocr(self.device.image)
            if total > 400 or used > total:
                # 页面刚加载时计数器可能粘连误解析（如 300 读成 3001），按识别失败处理
                used, remain, total = 0, 0, 0
            if total > 0:
                ocr_fail = 0
                if remain <= 0:
                    logger.info(f"[崽战退治] 今日消耗已达上限 {used}/{total}，收工")
                    self._cub_war_limit_reached = True
                    break
                if cost > 0 and remain < cost:
                    logger.info(f"[崽战退治] 剩余 {remain} 不足一次消耗 {cost}，收工")
                    self._cub_war_limit_reached = True
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

    def back_to_feast_map(self) -> bool:
        """
        从首领挑战页/区域详情页/活动主页逐级返回盛宴地图
        """
        timer = Timer(25).start()
        while not timer.reached():
            self.screenshot()
            if self.appear(self.I_CHECK_FEAST_MAP):
                return True
            if self.appear(self.I_CHECK_MAIN):
                logger.warning("[崽战退治] 返回途中已回到庭院，提前结束")
                return False
            if (self.appear(self.I_CHECK_CHALLENGE) or self.appear(self.I_CHECK_SHRINE)
                    or self.appear(self.I_CHECK_YOKAI) or self.appear(self.I_CHECK_CUB_WAR_PAGE)):
                self.click(RuleClick(roi_front=(14, 8, 44, 44), roi_back=(14, 8, 44, 44),
                                     name='CUB_WAR_PAGE_BACK'), interval=1.5)
        logger.warning("[崽战退治] 返回盛宴地图超时")
        return False

    def exit_cub_war(self) -> None:
        """
        从崽战活动内逐级返回庭院（挑战页/盛宴地图/区域详情页/活动主页共用左上角返回位）
        """
        timer = Timer(60).start()
        while not timer.reached():
            self.screenshot()
            if self.appear(self.I_CHECK_MAIN):
                logger.info("[崽战退治] 已返回庭院")
                return
            if (self.appear(self.I_CHECK_CHALLENGE) or self.appear(self.I_CHECK_FEAST_MAP)
                    or self.appear(self.I_CHECK_SHRINE) or self.appear(self.I_CHECK_YOKAI)
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
