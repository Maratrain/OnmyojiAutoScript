from pydantic import BaseModel, Field

from tasks.Component.config_base import ConfigBase, Time
from tasks.Component.config_scheduler import Scheduler
from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig


class Activity999Config(BaseModel):
    battle_count_limit: int = Field(
        default=0,
        ge=0,
        description='battle_count_limit_help',
    )
    run_time_limit: Time = Field(
        default=Time(hour=0, minute=0, second=0),
        description='run_time_limit_help',
    )


class Activity999(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    activity_999_config: Activity999Config = Field(default_factory=Activity999Config)
    general_battle_config: GeneralBattleConfig = Field(default_factory=GeneralBattleConfig)
