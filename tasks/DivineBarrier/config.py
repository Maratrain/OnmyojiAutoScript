# This Python file uses the following encoding: utf-8
from datetime import timedelta
from pydantic import Field
from tasks.Component.config_base import ConfigBase
from tasks.Component.config_scheduler import Scheduler


class DivineBarrierConfig(ConfigBase):
    run_count: int = Field(
        default=1, ge=0, le=999, title='执行次数',
        description='0 表示持续挑战，直到体力或活动券不足；大于 0 时完成指定次数后停止。')
    limit_time: timedelta = Field(
        default=timedelta(minutes=30), title='最长运行时间',
        description='达到时间后安全结束。')


class DivineBarrier(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    divine_barrier_config: DivineBarrierConfig = Field(default_factory=DivineBarrierConfig)
