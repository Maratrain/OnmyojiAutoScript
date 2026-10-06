from pydantic import BaseModel, Field
from tasks.Component.config_scheduler import Scheduler
from tasks.Component.config_base import ConfigBase


class LevelRushConfig(BaseModel):
    exploration_chapter_max_15_enable: bool = Field(
        default=True,
        description='开启后章节超过困难十五章会自动降级，不开就得手动配阵容，不然打不过',
    )
    skip_to_30_stop_enable: bool = Field(
        default=True,
        description='触发跳过剧情后领取奖励并直接结束任务',
    )
    level_7_mark: bool = Field(
        default=False,
        description='进度标记：已完成七级前剧情，自动勾选，请勿手动设置',
    )
    assist_up_mark: bool = Field(
        default=False,
        description='进度标记：已借取SP姑获鸟并上阵，自动勾选，请勿手动设置',
    )
    get_achievement_reward_mark: bool = Field(
        default=False,
        description='进度标记：已领取成就等勾玉奖励并购买体力，自动勾选，请勿手动设置',
    )
    skip_to_30_mark: bool = Field(
        default=False,
        description='进度标记：已触发跳过剧情，自动勾选，请勿手动设置',
    )


class LevelRush(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    level_rush_config: LevelRushConfig = Field(default_factory=LevelRushConfig)
