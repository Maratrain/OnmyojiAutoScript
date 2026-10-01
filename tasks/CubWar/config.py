# This Python file uses the following encoding: utf-8
from pydantic import Field

from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.SwitchSoul.switch_soul_config import SwitchSoulConfig
from tasks.Component.config_scheduler import Scheduler
from tasks.Component.config_base import ConfigBase


class CubWar(ConfigBase):
    # 为崽而战·八百八狸盛宴（限时活动）：boss 每天 14:00 开启，建议调度时间设在此之后
    scheduler: Scheduler = Field(default_factory=Scheduler)
    general_battle: GeneralBattleConfig = Field(default_factory=GeneralBattleConfig)
    switch_soul_config: SwitchSoulConfig = Field(default_factory=SwitchSoulConfig)
