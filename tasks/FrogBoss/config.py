# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey

from enum import Enum
from pydantic import BaseModel, Field

from tasks.Component.config_base import ConfigBase, MultiLine, Time
from tasks.Component.config_scheduler import Scheduler


class Strategy(str, Enum):
    Majority = 'frog_majority'
    Minority = 'frog_minority'
    Bilibili = 'frog_bilibili'
    Dashen = 'frog_dashen'
    Oas = 'frog_oas'
    FollowBlogger = 'frog_follow_blogger'
    AlwaysRed = 'frog_always_red'
    AlwaysBlue = 'frog_always_blue'

class FrogBossConfig(ConfigBase):
    before_end_frog: Time = Field(default=Time(0, 15, 0), description='before_end_frog_help')
    strategy_frog: Strategy = Field(default=Strategy.Majority, description='strategy_frog_help')
    follow_bloggers: str = Field(default='面灵气喵,徐清林', description='follow_bloggers_help')
    notify_enable: bool = Field(default=False, description='frog_notify_enable_help')
    notify_config: MultiLine = Field(default='provider: null', description='frog_notify_config_help')

class FrogBoss(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    frog_boss_config: FrogBossConfig = Field(default_factory=FrogBossConfig)



