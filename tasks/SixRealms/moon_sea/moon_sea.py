import time

import random
from module.atom.click import RuleClick
from module.atom.image import RuleImage
from module.base.timer import Timer
from module.exception import TaskEnd, GameStuckError
from module.logger import logger
from tasks.SixRealms.moon_sea.base_moon_sea import BaseMoonSea

import tasks.SixRealms.moon_sea.page as pages
from typing import Callable


class MoonSeaExhausted(Exception):
    """双倍奖励耗尽等入场前终止信号，由 SixRealms 捕获后收尾"""


class MoonSea(BaseMoonSea):
    """月之海"""

    def _default_detect_categories(self) -> set[str]:
        categories = super()._default_detect_categories()
        categories.add("six_realms")
        categories.add("moon_sea")
        return categories

    @property
    def ms_page_handle_dict(self) -> dict[pages.Page, Callable]:
        return {
            pages.page_moon_sea: self.run_on_ms,
            pages.page_ms_prepare: self.run_on_ms_prepare,
            pages.page_ms_main: self.run_on_ms_main,
            pages.page_ms_shop_land: self.run_on_ms_store,
            pages.page_ms_mistery_land: self.run_on_ms_mistery,
            pages.page_ms_chaos_land: self.run_on_ms_chaos,
            pages.page_ms_star_land: self.run_on_ms_star,
            pages.page_ms_battle_land: self.run_on_ms_battle,
            pages.page_ms_challenge: self.run_on_ms_challenge,
            pages.page_ms_map: lambda : self.goto_page(pages.page_ms_main),
            pages.page_ms_exit: lambda : self.click(pages.random_click(ltrb=(True, False, False, False)), interval=1.2),
            pages.page_sr_prepare_exit: lambda : self.goto_page(pages.page_ms_prepare),
            pages.page_sr_open_store: lambda : self.goto_page(pages.page_ms_main),
            pages.page_battle_prepare: self.run_on_ms_challenge,
            pages.page_battle: self.run_on_ms_challenge,
            pages.page_battle_result: self.run_on_ms_challenge,
            pages.page_reward: lambda : self.click(pages.random_click(), interval=1.2),
        }

    def run(self):
        self.before_run()
        logger.hr('月之海', 1)
        while True:
            self.screenshot()
            current_page = self.get_current_page()
            if current_page is None:
                time.sleep(0.5)
                continue
            handle = self.ms_page_handle_dict.get(current_page, None)
            if handle is None:
                self.goto_page(pages.page_moon_sea)
                continue
            try:
                handle()
            except TaskEnd:
                break
        logger.info('[六道-月之海] 月之海任务结束')

    def read_double_reward_count(self) -> int:
        """读入场页右上角的双倍奖励剩余次数，两次连续相同读数才算稳定"""
        previous = None
        for _ in range(4):
            self.screenshot()
            if not (self.appear(self.I_MSTART) or self.appear(self.I_MCONINUE)):
                previous = None
                continue
            text = str(self.O_MS_DOUBLE_COUNT.ocr(self.device.image)).strip()
            if not text or not text.isascii() or not text.isdigit():
                previous = None
                continue
            count = int(text)
            if count == previous:
                logger.info(f'[六道-月之海] 双倍奖励剩余次数: {count}')
                return count
            previous = count
            time.sleep(0.3)
        raise GameStuckError('[六道-月之海] 无法确认入场页双倍奖励剩余次数')

    def run_on_ms(self):
        """月之海界面"""
        if self.config.model.six_realms.six_realms_gate.double_rewards_only \
                and (self.appear(self.I_MSTART) or self.appear(self.I_MCONINUE)):
            # 只打双倍奖励：入场前先查剩余次数，为 0 时保留未完成进度提前收尾
            if self.read_double_reward_count() == 0:
                logger.info('[六道-月之海] 无剩余双倍奖励，保留未完成进度，提前结束')
                raise MoonSeaExhausted
        if self.appear_then_click(self.I_MCONINUE, interval=1):
            return
        if self.appear_then_click(self.I_MSTART, interval=1):
            return

    def run_on_ms_prepare(self):
        """进入月之海主界面前的准备界面"""
        if self.appear_then_click(self.I_MSTART_CONFIRM, interval=1.5) or \
                self.appear_then_click(self.I_MSTART_CONFIRM2, interval=1.5):
            return
        if self.appear_then_click(self.I_MFIRST_SKILL, interval=1.5):
            self.cnt_skill101 = 1
            return

    def _read_remain_turns_stable(self) -> int:
        """剩余回合数连读两次一致才采信，防止单帧把 17 误读成 1 提前召唤商店；不稳定按 99 保守处理"""
        previous = None
        for _ in range(4):
            self.screenshot()
            value = self.get_remain_turns(self.O_REMAIN_TURNS)
            if value == previous:
                return value
            previous = value
        logger.warning(f'[六道-月之海] 剩余回合数读数不稳定: {previous}，本轮不召唤商店')
        return 99

    def _filter_island(self, appeared_islands: list[RuleImage]) -> list[RuleImage]:
        remain_turns = self._read_remain_turns_stable()
        appeared_shop = self.appear(self.I_MS_LAND_SHOP)
        # 剩余回合数<=2&商店未出现&技能未满&金币足够打开商店和买柔风, 则开启商店
        if remain_turns <= 2 and not appeared_shop and self.cnt_skill101 < 5 and self.coin_num >= 400:
            self.open_shop(self.I_M_STORE_ACTIVITY, pages.page_ms_shop_land)
            return []
        # 出现商店&岛屿数量>2&金币不够买柔风&剩余回合数>1, 则不选择商店, 先攒金币
        if appeared_shop and len(appeared_islands) >= 2 and self.coin_num < 300 and remain_turns > 1:
            logger.info('[六道-月之海] 钱币不足，选择其他岛屿')
            appeared_islands.remove(self.I_MS_LAND_SHOP)
        return appeared_islands

    def run_on_ms_main(self):
        """月之海主界面 执行策略选岛屿"""
        if self.appear(self.I_BOSS_FIRE_PREPARE) and \
                self.enter_battle(self.I_BOSS_FIRE, boss_unlock=self.I_BOSS_TEAM_UNLOCK):
            logger.info('[六道-月之海] 开始首领战斗')
            self.run_general_battle(battle_key='boss', exit_matcher=pages.page_moon_sea)
            raise TaskEnd
        # 优先级：商店 > 神秘 > 混沌 > 星之屿 > 战斗
        islands = [self.I_MS_LAND_SHOP, self.I_MS_LAND_MYSTERY, self.I_MS_LAND_CHAOS, self.I_MS_LAND_STAR, self.I_MS_LAND_FIRE]
        self.choose_and_enter_island(islands)

    def run_on_ms_challenge(self):
        """月之海挑战界面"""
        if self.enter_battle(self.I_BATTLE_FIRE):
            self.run_general_battle(battle_key="normal", exit_matcher=pages.page_ms_main)

    def run_on_ms_store(self):
        """宁息商店"""
        logger.hr('宁息之屿')
        if self.cnt_skill101 >= 5:
            logger.info('[六道-月之海] 技能已满级，跳过购物')
            self.goto_page(pages.page_ms_main)
            return
        self.coin_num, buy_times = self.buy_skill(self.I_STORE_SKILL_101, 300, self.O_COIN_NUM,
                                       self.I_STORE_REFRESH, self.O_STORE_REFRESH_TIME)
        self.cnt_skill101 += buy_times
        logger.info(f'[六道-月之海] 柔风等级: {self.cnt_skill101}')
        self.goto_page(pages.page_ms_main)

    def _leave_mistery_island(self):
        """离开神秘之屿：先处理「是否离开」确认弹窗（勾选不再提示再确认），否则弹窗会挡住返回"""
        timeout = Timer(20).start()
        while not timeout.reached():
            self.screenshot()
            if self.get_current_page() == pages.page_ms_main:
                return
            if self.appear(self.I_MS_LEAVE_TITLE):
                if self.appear(self.I_MS_LEAVE_UNCHECKED):
                    self.click(self.I_MS_LEAVE_UNCHECKED, interval=1)
                    continue
                self.appear_then_click(self.I_MS_LEAVE_CONFIRM, interval=1.5)
                continue
            self.appear_then_click(self.I_UI_BACK_BLUE, interval=3)
        raise GameStuckError('[六道-月之海] 未能离开神秘之屿')

    def run_on_ms_mistery(self):
        """神秘之屿 转换/仿造"""
        logger.hr('神秘之屿')
        if not self.appear(self.I_MISTERY_IMITATE):
            logger.info('[六道-月之海] 无可转换技能')
            self._leave_mistery_island()
            return
        logger.info('[六道-月之海] 仿造技能')
        if self.cnt_skill101 >= 5:
            logger.info('[六道-月之海] 技能已满级，跳过仿造')
            self._leave_mistery_island()
            return
        if not self.appear_then_click(self.I_MISTERY_IMITATE_SKILL_101):
            self._leave_mistery_island()
            return
        # 每次进岛只允许一次选择和一次提交：动画延迟不是开第二次仿造弹窗的理由
        submitted = False
        imitated = False
        dismiss = RuleClick(roi_front=(550, 570, 180, 50), roi_back=(550, 570, 180, 50),
                            name='ms_imitate_success_dismiss')
        timeout = Timer(25).start()
        while not timeout.reached():
            self.screenshot()
            if self.get_current_page() == pages.page_ms_main:
                break
            if self.appear(self.I_MISTERY_IMITATE_SUCCESS):
                if not imitated:
                    imitated = True
                    self.cnt_skill101 = min(5, self.cnt_skill101 + 1)
                    logger.info(f'[六道-月之海] 柔风等级: {self.cnt_skill101}')
                self.click(dismiss, interval=1.5)
                continue
            if self.click_ui_confirm(interval=1.5):
                continue
            if submitted and not imitated:
                # 已提交未出结果：等待，不再点仿造按钮
                continue
            if imitated:
                # 仿造成功后若仍留在岛上（仿造按钮还在），直接离开
                if self.appear(self.I_MISTERY_IMITATE):
                    self._leave_mistery_island()
                    return
                continue
            if self.appear_then_click(self.I_MISTERY_IMITATE, interval=2.5):
                submitted = True
        else:
            raise GameStuckError('[六道-月之海] 仿造结果未确认（单次提交后 25 秒内无结果）')
        logger.info('[六道-月之海] 仿造完成')
        self._leave_mistery_island()

    def run_on_ms_chaos(self):
        """混沌之屿 宝箱/精英"""
        logger.hr('混沌之屿')
        is_box: bool = self.appear(self.I_CHAOS_BOX_EXIT)
        if is_box:
            logger.info('[六道-月之海] 不领取宝箱')
            self.goto_page(pages.page_ms_main)
            return
        self.ui_click(self.C_NPC_FIRE_CENTER, self.I_BATTLE_FIRE, interval=0.8)
        if self.enter_battle(self.I_BATTLE_FIRE):
            logger.info('[六道-月之海] 开始精英战斗')
            self.run_general_battle(battle_key="elite", exit_matcher=pages.page_ms_main)

    def run_on_ms_star(self):
        """星之屿 红蛋/星之子"""
        logger.hr('星之屿')
        self.ui_click(self.C_NPC_FIRE_LEFT, self.I_BATTLE_FIRE, interval=0.8)
        if self.enter_battle(self.I_BATTLE_FIRE):
            logger.info('[六道-月之海] 开始红蛋战斗')
            self.run_general_battle(battle_key="normal", exit_matcher=pages.page_ms_main)

    def run_on_ms_battle(self):
        """鏖战之屿 普通怪"""
        logger.hr('鏖战之屿')
        self.ui_click(self.C_NPC_FIRE_RIGHT, self.I_BATTLE_FIRE, interval=0.8)
        if self.enter_battle(self.I_BATTLE_FIRE):
            logger.info('[六道-月之海] 开始普通战斗')
            self.run_general_battle(battle_key="normal", exit_matcher=pages.page_ms_main)


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('日常1')
    d = Device(c)
    t = MoonSea(c, d)
    t.screenshot()

    t.run_moon_sea()
