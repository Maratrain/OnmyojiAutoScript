from pydantic import BaseModel, Field

from tasks.Component.config_base import ConfigBase, Time
from tasks.Component.config_scheduler import Scheduler
from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig


class Activity999Config(BaseModel):
    battle_count_limit: int = Field(
        default=0,
        ge=0,
        title='战斗次数上限',
        description='完成指定次数后停止；0 表示不限制，直到活动次数耗尽',
    )
    run_time_limit: Time = Field(
        default=Time(hour=0, minute=0, second=0),
        title='最长运行时间',
        description='到达该时长后安全结束；0 表示不限制',
    )


class Activity999(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    activity_999_config: Activity999Config = Field(default_factory=Activity999Config)
    general_battle_config: GeneralBattleConfig = Field(default_factory=GeneralBattleConfig)
