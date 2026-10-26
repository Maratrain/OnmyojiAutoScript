# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from datetime import datetime
from pydantic import BaseModel, Field

from tasks.Component.config_scheduler import Scheduler
from tasks.Component.config_base import ConfigBase, dynamic_hide, DateTime, MultiLine
from enum import Enum


class SummonType(str, Enum):
    default = '普通召唤'
    recall = '今忆召唤'


class DoneRecord(ConfigBase):
    courtyard_affairs_dt: DateTime = Field(default=DateTime.fromisoformat("2023-01-01 00:00:00"))
    pickup_email_dt: DateTime = Field(default=DateTime.fromisoformat("2023-01-01 00:00:00"))
    summon_dt: DateTime = Field(default=DateTime.fromisoformat("2023-01-01 00:00:00"))
    guild_donate_dt: DateTime = Field(default=DateTime.fromisoformat("2023-01-01 00:00:00"))
    luck_msg_dt: DateTime = Field(default=DateTime.fromisoformat("2023-01-01 00:00:00"))
    store_sign_dt: DateTime = Field(default=DateTime.fromisoformat("2023-01-01 00:00:00"))
    sushi_dt: DateTime = Field(default=DateTime.fromisoformat("2023-01-01 00:00:00"))
    friend_like_dt: DateTime = Field(default=DateTime.fromisoformat("2023-01-01 00:00:00"))
    guild_donate_finish: bool = Field(default=False)


class IncomeSnapshot(ConfigBase):
    """一次收益快照。读不到的项目留 -1，不要用 0 顶替，否则差值会凭空多出来。"""
    dt: DateTime = Field(default=DateTime.fromisoformat("2023-01-01 00:00:00"))
    # 庭院
    gold: int = Field(default=-1)
    jade: int = Field(default=-1)
    ap: int = Field(default=-1)
    # 秘卷屋
    sca_orochi_scales: int = Field(default=-1)
    sca_reverse_scale: int = Field(default=-1)
    sca_demon_souls: int = Field(default=-1)
    sca_picture_book: int = Field(default=-1)
    # 商城
    mystery_amulet: int = Field(default=-1)


class DailyGuildDonate(ConfigBase):
    enable: bool = Field(default=False)
    auto_get_rewards: bool = Field(default=True)
    notify_enable: bool = Field(default=False, description='guild_donate_notify_help')
    guild_member_list: MultiLine = Field(default='', description='guild_member_list_help')
    friend_list: MultiLine = Field(default='', description='invite_friend_list_help')
    name_check: bool = Field(default=True, description='guild_donate_name_check_help')

    @property
    def guild_member_list_v(self) -> list[str]:
        if not self.guild_member_list or self.guild_member_list == '' or self.guild_member_list.strip() == '' or \
                len(self.guild_member_list.split('\n')) == 0:
            return []
        return [line.strip() for line in self.guild_member_list.split('\n') if line.strip() != '']

    @property
    def friend_list_v(self) -> list[str]:
        if not self.friend_list or self.friend_list == '' or self.friend_list.strip() == '' or \
                len(self.friend_list.split('\n')) == 0:
            return []
        return [line.strip() for line in self.friend_list.split('\n') if line.strip() != '']


class DailyFriendLike(ConfigBase):
    enable: bool = Field(default=False)
    # 要点赞的好友名字，每行一个；同区好友直接填名字，重名的跨区好友才用 名字@区服名 区分
    like_names: MultiLine = Field(default='', description='要点赞的好友名字，每行一个；同区好友直接填名字，重名的跨区好友才需加 @区服名')
    # 名单为空时改为点赞全部好友（含跨区），至当日 20 次上限
    like_all: bool = Field(default=False, description='好友名单为空时生效：点赞全部好友至当日 20 次上限')
    # 打开聊天面板后核对名字与区服，防止重名/点错行
    name_check: bool = Field(default=True, description='点赞前核对聊天面板顶部名字与紫色区服名，防止点错人')
    # 搜索点赞目标，每行一个，支持 #玩家ID 或名字（可点赞非好友）；搜索固定使用全服
    search_names: MultiLine = Field(default='', description='搜索点赞目标，每行一个，支持 #玩家ID 或名字；搜索固定使用全服')

    @property
    def like_names_v(self) -> list[tuple[str, str]]:
        """每行解析为 (名字, 区服名)；不带 @ 时区服名为空串，表示不校验区服"""
        if not self.like_names or self.like_names == '' or self.like_names.strip() == '':
            return []
        entries = []
        for line in self.like_names.split('\n'):
            line = line.strip()
            if not line:
                continue
            if '@' in line:
                name, server = line.rsplit('@', 1)
                entries.append((name.strip(), server.strip()))
            else:
                entries.append((line, ''))
        return entries

    @property
    def search_names_v(self) -> list[str]:
        if not self.search_names or self.search_names == '' or self.search_names.strip() == '' or \
                len(self.search_names.split('\n')) == 0:
            return []
        return [line.strip() for line in self.search_names.split('\n') if line.strip() != '']


class DailyTriflesConfig(BaseModel):
    # 庭院事务
    courtyard_affairs: bool = Field(default=True)
    # 收取邮件
    pickup_email: bool = Field(default=True)
    one_summon: bool = Field(title='One Summon', default=False)
    # 召唤类型
    summon_type: SummonType = Field(default=SummonType.default, description='召唤类型')
    # 是否绘制神秘图案
    draw_mystery_pattern: bool = Field(title='Draw Mystery Pattern', default=False, description='是否绘制神秘图案')
    luck_msg: bool = Field(title='Luck Msg', default=False)
    store_sign: bool = Field(title='Store Sign', default=False, description='store_sign_help')
    # 每天购买体力数量
    buy_sushi_count: int = Field(title='Buy Sushi Count', default=-1)
    # 统计每日收益
    income_stat: bool = Field(title='统计每日收益', default=False)

    hide_fields = dynamic_hide('draw_mystery_pattern')


class DailyTrifles(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    trifles_config: DailyTriflesConfig = Field(default_factory=DailyTriflesConfig)
    guild_donate: DailyGuildDonate = Field(default_factory=DailyGuildDonate)
    friend_like: DailyFriendLike = Field(default_factory=DailyFriendLike)
    done_record: DoneRecord = Field(default_factory=DoneRecord)

    hide_fields = dynamic_hide('done_record')

    def today_is_done(self, mode: str) -> bool:
        """对应mode今天是否已经完成"""
        done_dt = getattr(self.done_record, f'{mode}_dt', None)
        if done_dt is None:
            return False
        if mode == 'guild_donate':
            if done_dt.date() != datetime.today().date():
                self.done_record.guild_donate_finish = False
            return self.done_record.guild_donate_finish
        return done_dt.date() == datetime.today().date()
