# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from enum import Enum

from pydantic import BaseModel, Field
from tasks.Component.config_base import dynamic_hide


class GreenMarkType(str, Enum):
    GREEN_LEFT1 = 'green_left1'
    GREEN_LEFT2 = 'green_left2'
    GREEN_LEFT3 = 'green_left3'
    GREEN_LEFT4 = 'green_left4'
    GREEN_LEFT5 = 'green_left5'
    GREEN_MAIN = 'green_main'


class GreenMarkEnum(str, Enum):
    CHOOSE = 'choose'
    NAME = 'name'


class GeneralBattleConfig(BaseModel):

    # 是否锁定阵容, 有些的战斗是外边的锁定阵容甚至有些的战斗没有锁定阵容的
    lock_team_enable: bool = Field(
        default=False, title='锁定阵容',
        description='战斗前点击锁定阵容按钮，无需每次手动确认',
    )

    # 是否启动 预设队伍
    preset_enable: bool = Field(
        default=False, title='启用预设队伍',
        description='战斗前切换到预设的队伍配置',
    )
    # 选哪一个预设组
    preset_group: int = Field(
        default=1, title='预设组', ge=1, le=7,
        description='使用第几个预设分组',
    )
    # 选哪一个队伍
    preset_team: int = Field(
        default=1, title='预设队伍', ge=1, le=5,
        description='分组内使用第几个队伍',
    )
    # 是否开启绿标
    green_enable: bool = Field(
        default=False, title='启用绿标',
        description='战斗中给指定式神戴上绿标(优先出手)',
    )
    # 绿标类型
    green_mark_type: GreenMarkEnum = Field(default=GreenMarkEnum.CHOOSE, title='绿标类型',
                                           description='按位置直接点选，或按式神名称识别')
    # 选哪一个绿标
    green_mark: GreenMarkType = Field(
        default=GreenMarkType.GREEN_LEFT1, title='绿标位置',
        description='绿标点在队伍中的位置',
    )
    # 绿标式神的名称
    green_mark_name: str = Field(
        default='', title='绿标式神名',
        description='绿标类型为按名称时，填写式神名称',
    )
    # 是否启动战斗时随机点击或者随机滑动
    random_click_swipt_enable: bool = Field(
        default=False, title='战斗随机点击',
        description='战斗过程中随机点击或滑动，模拟人工操作',
    )

    # 战斗硬超时, None 表示回退到全局战斗接管配置
    battle_timeout: int = Field(
        default=-1, title='战斗超时(秒)', ge=-1,
        description='单场战斗硬超时秒数；-1 表示使用全局战斗接管配置',
    )
    # 结算后再次回到准备界面时是否自动继续
    continuous_battle: bool = Field(
        default=False, title='连续战斗',
        description='结算后回到准备界面时自动继续开战',
    )
    # 最大连战次数, 0 表示不限制
    max_continuous: int = Field(
        default=0, title='最大连战次数', ge=0,
        description='连续战斗的次数上限；0 表示不限制',
    )
    # 外部可在运行期间置位, 在准备/战斗中触发快速退出
    quick_exit: bool = Field(
        default=False, title='快速退出',
        description='运行期间置位后，在准备或战斗中触发快速退出',
    )

    hide_fields = dynamic_hide('continuous_battle', 'max_continuous', 'quick_exit')
