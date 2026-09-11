# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from datetime import timedelta, datetime
from pydantic import BaseModel, Field

from tasks.Component.config_scheduler import Scheduler
from tasks.Component.config_base import ConfigBase, DateTime, dynamic_hide
from tasks.Utils.config_enum import DemonClass


class ThousandThings(BaseModel):
    # 千物宝箱
    enable: bool = Field(title='启用', default=False)
    earn_money: bool = Field(title='金币妖怪', default=False, description='earn_money_help')
    mystery_amulet: bool = Field(title='神秘的护符', default=False)
    black_daruma_fragment: bool = Field(title='黑蛋碎片', default=False)
    ap: bool = Field(title='体力', default=False, description='ap_help')


class Consignment(BaseModel):
    # 寄售屋
    enable: bool = Field(title='启用', default=False)
    buy_sale_ticket: bool = Field(title='购买特售券', default=False, description='buy_sale_ticket_help')


class Scales(BaseModel):
    # 密卷屋 蛇皮
    enable: bool = Field(title='启用', default=False)
    orochi_scales: int = Field(title='八岐大蛇鳞片', default=40, description='orochi_scales_help')
    demon_souls: int = Field(title='御魂', default=50, description='demon_souls_help')
    demon_class: DemonClass = Field(title='御魂副本', default=DemonClass.TSUCHIGUMO, description='demon_class_help')
    demon_position: int = Field(title='御魂层数', default=1, description='demon_position_help')
    picture_book_scrap: int = Field(title='绘卷碎片', default=30, description='picture_book_scrap_help')
    enable_book_auto: bool = Field(title='启用绘卷自动选择', default=False, description='enable_book_auto_help')
    picture_book_rule: str = Field(title='绘卷选择规则', default='auto', description='picture_book_rule_help')


class SpecialRoom(BaseModel):
    # 杂货铺 特殊购买
    enable: bool = Field(title='启用', default=False)
    totem_pass: bool = Field(title='图腾通行证', default=False)
    medium_bondling_discs: int = Field(title='中号契约书', default=0, description='medium_bondling_discs_special')
    low_bondling_discs: int = Field(title='小号契约书', default=0, description='low_bondling_discs_special')


class HonorRoom(BaseModel):
    # 杂货铺 荣誉购买
    enable: bool = Field(title='启用', default=False)
    mystery_amulet: bool = Field(title='神秘的护符', default=False, description='mystery_amulet_help_honor')
    black_daruma_scrap: bool = Field(title='黑蛋碎片', default=False, description='black_daruma_scrap_help_honor')


class FriendshipPoints(BaseModel):
    # 杂货铺 友情点
    enable: bool = Field(title='启用', default=False)
    white_daruma: bool = Field(title='白蛋', default=False)
    red_daruma: int = Field(title='红蛋', default=0)
    broken_amulet: int = Field(title='破碎的护符', default=0)


class MedalRoom(BaseModel):
    # 杂货铺 勋章购买
    enable: bool = Field(title='启用', default=False)
    black_daruma: bool = Field(title='黑蛋', default=False)
    mystery_amulet: bool = Field(title='神秘的护符', default=False)
    ap_100: bool = Field(title='100体力', default=False)
    random_soul: bool = Field(title='随机御魂', default=False)
    white_daruma: bool = Field(title='白蛋', default=False)
    challenge_pass: int = Field(title='挑战券', default=0, description='challenge_pass_help')
    red_daruma: int = Field(title='红蛋', default=0)
    broken_amulet: int = Field(title='破碎的护符', default=0)


class Charisma(BaseModel):
    # 杂货铺 魅力购买
    enable: bool = Field(title='启用', default=False)
    black_daruma_scrap: bool = Field(title='黑蛋碎片', default=False)
    mystery_amulet: bool = Field(title='神秘的护符', default=False)


class Shrine(BaseModel):
    # 神社 神龛
    enable: bool = Field(title='启用', default=False)
    black_daruma: bool = Field(title='黑蛋', default=False)
    white_daruma_five: bool = Field(title='5星白蛋', default=False)
    white_daruma_four: bool = Field(title='4星白蛋', default=False)


class Bondlings(BaseModel):
    # 契灵商店 契忆
    enable: bool = Field(title='启用', default=False)
    random_soul: int = Field(title='随机御魂', default=0, description='random_soul_help')
    bondling_stone: int = Field(title='契约石', default=0, description='bondling_stone_help')
    high_bondling_discs: int = Field(title='大号契约书', default=0, description='high_bondling_discs_help')
    medium_bondling_discs: int = Field(title='中号契约书', default=0, description='medium_bondling_discs_help')


class GuildStore(BaseModel):
    # 寮商店
    enable: bool = Field(title='启用', default=False)
    honor_gift: bool = Field(default=False)
    mystery_amulet: bool = Field(title='神秘的护符', default=False)
    black_daruma_scrap: bool = Field(title='黑蛋碎片', default=False)
    skin_ticket: int = Field(title='皮肤券', default=0, description='skin_ticket_help')


class ItachiCoinShop(BaseModel):
    # 鼬乐币商店
    itachi_coin_buy_jade: bool = Field(
        default=False,
        description='itachi_coin_buy_jade_help',
    )


class WeeklyPurchase(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    itachi_coin_shop: ItachiCoinShop = Field(default_factory=ItachiCoinShop)
    special_room: SpecialRoom = Field(default_factory=SpecialRoom)
    honor_room: HonorRoom = Field(default_factory=HonorRoom)
    friendship_points: FriendshipPoints = Field(default_factory=FriendshipPoints)
    medal_room: MedalRoom = Field(default_factory=MedalRoom)
    charisma: Charisma = Field(default_factory=Charisma)

    thousand_things: ThousandThings = Field(default_factory=ThousandThings)
    consignment: Consignment = Field(default_factory=Consignment)
    scales: Scales = Field(default_factory=Scales)
    bondlings: Bondlings = Field(default_factory=Bondlings)
    shrine: Shrine = Field(default_factory=Shrine)
    guild_store: GuildStore = Field(default_factory=GuildStore)
