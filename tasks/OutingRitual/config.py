# This Python file uses the following encoding: utf-8
from datetime import timedelta

from pydantic import Field

from tasks.Component.config_base import ConfigBase
from tasks.Component.config_scheduler import Scheduler


class OutingRitualConfig(ConfigBase):
    run_count: int = Field(
        default=0, ge=0, le=999, title='执行次数',
        description='0 表示持续执行，直到活动次数不足；大于 0 时完成指定次数后停止。')
    limit_time: timedelta = Field(
        default=timedelta(minutes=30), title='最长运行时间',
        description='到达时间后安全结束，防止活动界面异常时无限等待。')


class OutingRitual(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    outing_ritual_config: OutingRitualConfig = Field(default_factory=OutingRitualConfig)
