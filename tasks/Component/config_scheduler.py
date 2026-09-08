# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from pydantic import Field

from tasks.Component.config_base import ConfigBase, TimeDelta, DateTime, Time

class Scheduler(ConfigBase):
    enable: bool = Field(
        default=False, title='启用',
        description='是否启用该任务',
    )
    next_run: DateTime = Field(
        default=DateTime.fromisoformat("2023-01-01 00:00:00"),
        title='下次运行',
        description='计划的下一次运行时间',
    )
    priority: int = Field(
        default=5, title='优先级',
        description='同时到期时数值越小越先执行',
    )

    success_interval: TimeDelta = Field(
        default=TimeDelta(days=1), title='成功间隔',
        description='任务成功后到下次运行的间隔',
    )
    failure_interval: TimeDelta = Field(
        default=TimeDelta(days=1), title='失败间隔',
        description='任务失败后到下次运行的间隔',
    )
    server_update: Time = Field(
        default=Time(hour=9, minute=0, second=0), title='服务器刷新',
        description='每日刷新时刻；错过当日时点的任务顺延到该时刻之后',
    )
    delay_date: int = Field(
        default=1, title='顺延天数', ge=1, le=31,
        description='任务错过每日刷新后顺延的天数',
    )
    float_time: Time = Field(
        default=Time(hour=0, minute=0, second=0), title='浮动时间',
        description='下次运行时间在 0 到该时长之间随机浮动，模拟人工使用',
    )


if __name__ == "__main__":
    dict_s = {
        "enable": False,
        "next_run": "2026-07-19T14:15:37",
        "priority": 5,
        "success_interval": "10 00:00:01",
        "failure_interval": "10 00:00:01",
        "server_update": "09:03:00",
        "float_time": "02:00:05"
    }
    s = Scheduler(**dict_s)
    print(s.model_dump())



