# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from datetime import timedelta, time

from pydantic import BaseModel, Field, validator

from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.QuickLoadout.config import NamedQuickLoadoutConfig
from tasks.Component.config_scheduler import Scheduler
from tasks.Component.config_base import ConfigBase, Time


class MartialTournamentConfig(ConfigBase):
    """武林大会活动配置"""
    limit_time: Time = Field(default=Time(hour=1, minute=30), title='最长运行时间',
                             description='到达该时长后安全结束任务')
    run_sequence: str = Field(default='pass,ap', title='运行顺序',
                              description='爬塔类型与先后顺序，逗号分隔：pass=名帖(券)爬塔, ap=体力爬塔')
    pass_limit: int = Field(default=50, title='名帖爬塔次数',
                            description='名帖(券)爬塔的目标次数')
    ap_limit: int = Field(default=300, title='体力爬塔上限',
                          description='体力爬塔消耗的体力上限')
    # 开启使用注灵搜寻券
    use_pass_2: bool = Field(default=False, title='使用注灵搜寻券',
                             description='名帖不足时改用注灵搜寻券继续爬塔')
    # 结束后激活御魂清理
    active_souls_clean: bool = Field(default=False, title='结束后清理御魂',
                                     description='任务结束后自动激活御魂清理')
    # 点击战斗随机休息
    random_sleep: bool = Field(default=False, title='战斗前随机休息',
                               description='点击战斗前随机等待一段时间，模拟人工操作')

    @property
    def limit_time_v(self) -> timedelta:
        if isinstance(self.limit_time, time):
            return timedelta(hours=self.limit_time.hour, minutes=self.limit_time.minute,
                             seconds=self.limit_time.second)
        return self.limit_time

    @property
    def sequence_list(self) -> list:
        """根据运行顺序返回启用的爬塔类型列表"""
        str_list = [climb_type.strip() for climb_type in self.run_sequence.split(',')]
        return [climb_type for climb_type in str_list if getattr(self, f'{climb_type}_limit', 0) > 0]

    @validator('limit_time', pre=True, always=True)
    def parse_limit_time(cls, value):
        if isinstance(value, str):
            if value.isdigit():
                try:
                    value = int(value)
                except ValueError:
                    return time(hour=0, minute=30, second=0)
                delta = timedelta(seconds=value)
                return time(hour=delta.seconds // 3600, minute=delta.seconds // 60 % 60, second=delta.seconds % 60)
            else:
                try:
                    return time.fromisoformat(value)
                except ValueError:
                    return time(hour=0, minute=30, second=0)
        return value


class SwitchSoulConfig(BaseModel):
    # 群体boss御魂配置
    enable_switch_group: bool = Field(default=False, title='切换群体Boss御魂',
                                      description='打群体Boss前切换到指定御魂队伍')
    group_boss_team: str = Field(default='-1,-1', title='群体Boss队伍编号',
                                 description='组1-7,队伍1-4，中间用英文逗号分隔')
    enable_switch_group_by_name: bool = Field(default=False, title='按名称切换群体Boss御魂',
                                              description='改用预设队伍名称切换')
    group_boss_team_name: str = Field(default='', title='群体Boss队伍名称',
                                      description='组名,队伍名，中间用英文逗号分隔')
    # 单体boss御魂配置
    enable_switch_single: bool = Field(default=False, title='切换单体Boss御魂',
                                       description='打单体Boss前切换到指定御魂队伍')
    single_group_team: str = Field(default='-1,-1', title='单体Boss队伍编号',
                                   description='组1-7,队伍1-4，中间用英文逗号分隔')
    enable_switch_single_by_name: bool = Field(default=False, title='按名称切换单体Boss御魂',
                                               description='改用预设队伍名称切换')
    single_group_team_name: str = Field(default='', title='单体Boss队伍名称',
                                        description='组名,队伍名，中间用英文逗号分隔')
    # 体力爬塔御魂配置
    enable_switch_mt_ap: bool = Field(default=False, title='切换体力爬塔御魂',
                                      description='体力爬塔前切换到指定御魂队伍')
    mt_ap_team: str = Field(default='-1,-1', title='体力爬塔队伍编号',
                            description='组1-7,队伍1-4，中间用英文逗号分隔')
    enable_switch_mt_ap_by_name: bool = Field(default=False, title='按名称切换体力爬塔御魂',
                                              description='改用预设队伍名称切换')
    mt_ap_team_name: str = Field(default='', title='体力爬塔队伍名称',
                                 description='组名,队伍名，中间用英文逗号分隔')


class MartialTournament(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    general_climb: MartialTournamentConfig = Field(default_factory=MartialTournamentConfig)
    switch_soul_config: SwitchSoulConfig = Field(default_factory=SwitchSoulConfig)
    # 首领战一键配置
    boss_quick_loadout_config: NamedQuickLoadoutConfig = Field(
        default_factory=NamedQuickLoadoutConfig
    )
    # 群体boss战斗配置
    group_battle_conf: GeneralBattleConfig = Field(
        default_factory=lambda: GeneralBattleConfig(battle_timeout=600)
    )
    # 单体boss战斗配置
    single_battle_conf: GeneralBattleConfig = Field(
        default_factory=lambda: GeneralBattleConfig(battle_timeout=600)
    )
    # 体力爬塔战斗配置
    mt_ap_battle_conf: GeneralBattleConfig = Field(default_factory=GeneralBattleConfig)
