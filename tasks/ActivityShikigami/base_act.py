import time

from datetime import datetime, timedelta
import random
from tasks.Component.GeneralBattle.general_battle import (
    GeneralBattle,
    ExitMatcher,
    BattleContext,
    BattleAction,
)
from cached_property import cached_property

from module.atom.image import RuleImage
from module.base.protect import random_sleep
from module.base.timer import Timer
from module.exception import TaskEnd
from module.logger import logger

from tasks.base_task import BaseTask
from tasks.ActivityShikigami.assets import ActivityShikigamiAssets
from tasks.ActivityShikigami.config import GeneralBattleConfig, ActivityShikigami
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.GameUi.game_ui import GameUi
import tasks.ActivityShikigami.page as pages
from typing import Optional, Callable


class LimitTimeOut(Exception):
    pass


class LimitCountOut(Exception):
    pass


class TicketsNotEnough(Exception):
    pass


class StateMachine(BaseTask):
    run_idx: int = 0  # 当前爬塔类型
    _count_map = None
    _pre_tickets_map = None
    switch_souled: dict[str, bool] = {}

    @cached_property
    def conf(self) -> ActivityShikigami:
        return self.config.model.activity_shikigami

    @property
    def climb_type(self) -> str:
        if self.run_idx >= len(self.conf.general_climb.run_sequence_v):
            return self.conf.general_climb.run_sequence_v[-1]
        return self.conf.general_climb.run_sequence_v[self.run_idx]

    @property
    def count_map(self) -> dict[str, int]:
        """
        :return: key: climb type, value: run count
        """
        if not getattr(self, "_count_map", None):
            self._count_map = {
                climb_type: 0 for climb_type in self.conf.general_climb.run_sequence_v
            }
        return self._count_map

    @property
    def pre_tickets_map(self) -> dict[str, int]:
        """
        :return: key: climb type, value: pre tickets num
        """
        if not getattr(self, "_pre_tickets_map", None):
            self._pre_tickets_map = {
                climb_type: -1 for climb_type in self.conf.general_climb.run_sequence_v
            }
        return self._pre_tickets_map

    def update_status(self):
        """
        更新全局状态
        """

        def get_count() -> int:
            return self.count_map[self.climb_type]

        def get_limit() -> int:
            limit = getattr(self.conf.general_climb, f"{self.climb_type}_limit", 0)
            return 0 if not limit else limit

        # 超过运行时间
        if datetime.now() - self.start_time >= self.conf.general_climb.limit_time_v:
            logger.info(f'[爬塔] 爬塔类型 {self.climb_type} 时间已用完')
            raise LimitTimeOut
        # 次数达到限制
        if get_count() >= get_limit():
            logger.info(f'[爬塔] 爬塔类型 {self.climb_type} 已达次数上限')
            raise LimitCountOut

    def switch_next(self):
        """
        切换下一种爬塔类型
        :return: True 切换成功 or False
        """
        self.run_idx += 1
        if self.run_idx >= len(self.conf.general_climb.run_sequence_v):
            logger.info('[爬塔] 所有爬塔活动已完成')
            return False
        # 切换爬塔类型了, 恢复所有状态
        self.current_count = 0
        logger.hr(f'[爬塔] 切换到 {self.climb_type}', 2)
        return True


class BaseAct(StateMachine, GameUi, GeneralBattle, SwitchSoul, ActivityShikigamiAssets):
    """爬塔活动基类"""

    def _exit_matcher(self) -> ExitMatcher | None:
        return self.I_ACT_FIRE

    def _handle_result(
        self, context: BattleContext, config: GeneralBattleConfig
    ) -> BattleAction:
        if self.climb_type == "boss":
            self.appear_then_click(self.I_UI_BACK_RED, interval=1.5)
        return super()._handle_result(context, config)

    def before_run(self):
        pages.page_battle_result = self.navigator.resolve_page(pages.page_battle_result)
        pages.page_battle_result.recognizer = pages.any_of(
            self.I_UI_BACK_RED, pages.page_battle_result.recognizer
        )

    @property
    def act_page_handle_dict(self) -> dict[pages.Page, Callable]:
        """活动页面和处理器的映射"""
        return {
            pages.page_act_pass: self._run_pass,
            pages.page_act_ap: self._run_ap,
            pages.page_act_ap100: self._run_ap100,
            pages.page_act_boss: self._run_boss,
            pages.page_battle_prepare: lambda: self.run_general_battle(
                getattr(self.conf, f"{self.climb_type}_battle_conf"),
                battle_key=f"act_{self.climb_type}",
            ),
            pages.page_battle: lambda: self.run_general_battle(
                getattr(self.conf, f"{self.climb_type}_battle_conf"),
                battle_key=f"act_{self.climb_type}",
            ),
            pages.page_reward: lambda: self.click(
                pages.random_click(ltrb=(False, False, True, False)), interval=1.5
            ),
        }

    def run(self):
        self.before_run()
        for climb_type in self.conf.general_climb.run_sequence_v:
            logger.hr(f'[爬塔] 开始运行 {self.climb_type}', 1)
            dest_page: Optional[pages.Page] = getattr(
                pages, f"page_act_{climb_type}", None
            )
            if not dest_page:
                logger.warning(f'[爬塔] 不支持 {climb_type} 页面')
                continue
            self.goto_page(dest_page)
            cur_battle_conf = getattr(self.conf, f"{climb_type}_battle_conf")
            if cur_battle_conf is None:
                logger.warning(f'[爬塔] 不支持 {climb_type} 战斗配置')
                continue
            self.lock_team(cur_battle_conf)
            try:
                while True:
                    self.screenshot()
                    self.update_status()
                    current_page = self.get_current_page()
                    if current_page is None:
                        time.sleep(0.5)
                        continue
                    handle = self.act_page_handle_dict.get(current_page, None)
                    if handle is None:
                        self.goto_page(dest_page)
                        continue
                    handle()
            except (LimitCountOut, LimitTimeOut, TicketsNotEnough):
                pass
            finally:
                self.switch_next()  # 切换下一个爬塔类型
        self.goto_page(pages.page_main)
        if self.conf.general_climb.active_souls_clean:
            self.set_next_run(
                task="SoulsTidy", success=False, finish=False, target=datetime.now()
            )
        self.set_next_run(task="ActivityShikigami", success=True)
        raise TaskEnd

    def _run_pass(self):
        self._run_common()

    def _run_ap(self):
        self._run_common()

    def _run_ap100(self):
        self._run_common()

    def _run_boss(self):
        self._run_common()

    def _run_common(self):
        if not self.check_tickets_enough():
            logger.warning('[爬塔] 门票已用完，等待下次运行')
            raise TicketsNotEnough
        self.switch_soul(self.I_BATTLE_MAIN_TO_RECORDS)
        if self.conf.general_climb.random_sleep:
            random_sleep(probability=0.2)
        if self.enter_battle():
            self.count_map[self.climb_type] += 1
            self.run_general_battle(
                getattr(self.conf, f"{self.climb_type}_battle_conf"),
                battle_key=f"act_{self.climb_type}",
            )

    def enter_battle(self):
        click_times, max_times = 0, random.randint(3, 5)
        while True:
            self.screenshot()
            if self.is_in_battle(False):
                return True
            if click_times >= max_times:
                logger.warning(
                    f'[爬塔] {self.climb_type} 无法进入战斗，点击已达最大次数'
                )
                raise TicketsNotEnough
            if self.appear(self.I_UI_BACK_RED, interval=1):
                logger.warning(
                    f'[爬塔] {self.climb_type} 无法进入战斗，出现红色关闭按钮，可能门票不足'
                )
                raise TicketsNotEnough
            if self.appear_then_click(
                self.I_UI_CONFIRM_SAMLL, interval=1
            ) or self.appear_then_click(self.I_UI_CONFIRM, interval=1):
                continue
            if self.ocr_appear_click(self.O_FIRE, interval=1.5):
                self.device.click_record_clear()
                click_times += 1
                logger.info(f'[爬塔] 尝试点击战斗，剩余次数[{max_times - click_times}]')
                continue

    def switch_soul(self, enter_button: RuleImage):
        if self.switch_souled.get(self.climb_type, False):
            return
        self.switch_souled[self.climb_type] = True
        conf = self.conf.switch_soul_config
        enable_switch = getattr(conf, f"enable_switch_{self.climb_type}", False)
        enable_by_name = getattr(
            conf, f"enable_switch_{self.climb_type}_by_name", False
        )
        if not enable_switch and not enable_by_name:
            return
        logger.hr('[爬塔] 开始切换御魂', 2)
        conf.validate_switch_soul()
        self.ui_click(enter_button, stop=self.I_CHECK_RECORDS, interval=1)
        if enable_by_name:
            group, team = getattr(conf, f"{self.climb_type}_group_team_name").split(",")
            self.run_switch_soul_by_name(group, team)
        elif enable_switch:
            group_team = getattr(conf, f"{self.climb_type}_group_team")
            self.run_switch_soul(group_team)
        self.goto_page(getattr(pages, f"page_act_{self.climb_type}"))

    def lock_team(self, battle_conf: GeneralBattleConfig):
        """
        根据配置判断当前爬塔类型是否锁定阵容, 并执行锁定或解锁
        """
        enable = battle_conf.lock_team_enable
        if enable:
            logger.info(f'[爬塔] 锁定 {self.climb_type} 队伍')
            match self.climb_type:
                case "ap" | "boss":
                    self.ui_click(self.I_AP_UNLOCK, stop=self.I_AP_LOCK, interval=1.5)
                case _:
                    self.ui_click(self.I_UNLOCK, stop=self.I_LOCK, interval=1.5)
            return
        logger.info(f'[爬塔] 解锁 {self.climb_type} 队伍')
        match self.climb_type:
            case "ap" | "boss":
                self.ui_click(self.I_AP_LOCK, stop=self.I_AP_UNLOCK, interval=1.5)
            case _:
                self.ui_click(self.I_LOCK, stop=self.I_UNLOCK, interval=1.5)

    def check_tickets_enough(self) -> bool:
        """
        判断当前爬塔门票是否足够
        :return: True 可以运行 or False
        """
        logger.hr(f'[爬塔] 检查 {self.climb_type} 门票')
        self.screenshot()
        remain_times = 0
        if self.climb_type == "pass":
            remain_times = self.O_REMAIN_PASS.ocr_digit(self.device.image)
        if self.climb_type == "ap":
            remain_times = self.O_REMAIN_AP.ocr_digit(self.device.image)
        if self.climb_type == "boss":
            cur, remain_times, total = self.O_REMAIN_BOSS.ocr_digit_counter(
                self.device.image
            )
        if self.climb_type == "ap100":
            remain_times = self.O_REMAIN_AP100.ocr_digit(self.device.image)
        # 上一次识别的票的数量和这一次识别的数量差距大于1, 则认为票数量有误, 允许继续挑战
        if self.pre_tickets_map[self.climb_type] - remain_times > 1:
            self.pre_tickets_map[self.climb_type] -= 1
            return True
        self.pre_tickets_map[self.climb_type] = remain_times
        return remain_times > 0
