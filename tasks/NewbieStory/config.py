from pydantic import Field

from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.config_base import ConfigBase, Time
from tasks.Component.config_scheduler import Scheduler


class NewbieStoryConfig(ConfigBase):
    run_time: Time = Field(
        default=Time(minute=30),
        title='单次运行时长',
        description='到时后正常结束，避免无法识别的画面让任务无限运行',
    )


class NewbieStory(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    newbie_story_config: NewbieStoryConfig = Field(default_factory=NewbieStoryConfig)
    general_battle_config: GeneralBattleConfig = Field(default_factory=GeneralBattleConfig)
