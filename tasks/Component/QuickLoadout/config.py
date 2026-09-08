# This Python file uses the following encoding: utf-8
from enum import Enum

from pydantic import BaseModel, Field


class QuickLoadoutMode(str, Enum):
    NUMBER = 'mode_number'
    OCR = 'mode_ocr'


class QuickLoadoutMode(str, Enum):
    NUMBER = 'mode_number'
    OCR = 'mode_ocr'


class QuickLoadoutConfig(BaseModel):
    """战斗界面内的一键配置。"""

    # 是否启用战斗前一键配置
    enable: bool = Field(default=False, title='启用一键配置',
                         description='战斗前自动切换到预设队伍')
    # 预设选择模式：mode_number按编号选择，mode_ocr按名称识别
    mode: QuickLoadoutMode = Field(default=QuickLoadoutMode.NUMBER, title='选择模式',
                                   description='按编号或按名称(OCR)选择预设')
    # 一键配置左侧预设组编号
    group_number: int = Field(default=1, ge=1, le=7, title='预设组编号',
                              description='一键配置左侧的预设分组编号')
    # 所选预设组中的预设编号
    preset_number: int = Field(default=1, ge=1, title='预设编号',
                               description='所选分组内的预设编号')
    # OCR模式使用的预设组名称
    group_name: str = Field(default='', title='预设组名称',
                            description='按名称(OCR)模式使用的预设组名称')
    # OCR模式使用的预设名称
    preset_name: str = Field(default='', title='预设名称',
                             description='按名称(OCR)模式使用的预设名称')

    def validate_target(self) -> None:
        if self.mode != QuickLoadoutMode.OCR:
            return
        if not self.group_name.strip():
            raise ValueError('Quick loadout group name cannot be empty in OCR mode')
        if not self.preset_name.strip():
            raise ValueError('Quick loadout preset name cannot be empty in OCR mode')


class NamedQuickLoadoutConfig(QuickLoadoutConfig):
    """支持按任务关卡名称选择不同预设的一键配置。"""

    # 是否按任务提供的关卡名称OCR选择不同预设
    custom_preset_enable: bool = Field(default=False, title='按关卡切换预设',
                                       description='按任务提供的关卡名称(OCR)选择不同预设')
    # 格式：关卡名:(预设组,预设); ALL匹配未特别指定的关卡
    custom_preset: str = Field(default='ALL:(1,1);', title='关卡预设映射',
                               description='格式：关卡名:(预设组,预设)；ALL 匹配未特别指定的关卡')
