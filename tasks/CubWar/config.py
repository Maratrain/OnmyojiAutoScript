# This Python file uses the following encoding: utf-8
from enum import Enum
from pydantic import Field

from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.SwitchSoul.switch_soul_config import SwitchSoulConfig
from tasks.Component.config_scheduler import Scheduler
from tasks.Component.config_base import ConfigBase


class CubWarGroup(str, Enum):
    """盛宴地图所在分组：决定地图上哪种颜色的小人是本组可攻打的目标"""
    Whale = 'cub_war_whale'    # 鲸组（蓝色）
    Gull = 'cub_war_gull'      # 鸥组（黄色）
    Shark = 'cub_war_shark'    # 鲨组（红色）


class CubWarSettings(ConfigBase):
    """退治目标开关（任务模型顶层只能放嵌套组，原始类型字段必须包进组里，否则配置页 args 生成会 KeyError '$ref'）"""
    battle_boss: bool = Field(
        default=True, title='首领·八百八狸', description='battle_boss_help',
    )
    battle_shrine: bool = Field(
        default=False, title='神社区域', description='battle_shrine_help',
    )
    battle_yokai: bool = Field(
        default=False, title='妖怪退治', description='battle_yokai_help',
    )


class CubWar(ConfigBase):
    # 为崽而战·八百八狸盛宴（限时活动）：首领开启时间以游戏内倒计时为准（地图八百八狸处与首领页可见），
    # 且需所在分组占领相邻区域后解锁；未开启时任务会自动跳过
    scheduler: Scheduler = Field(default_factory=Scheduler)
    general_battle: GeneralBattleConfig = Field(default_factory=GeneralBattleConfig)
    switch_soul_config: SwitchSoulConfig = Field(default_factory=SwitchSoulConfig)
    cub_war_settings: CubWarSettings = Field(default_factory=CubWarSettings)
