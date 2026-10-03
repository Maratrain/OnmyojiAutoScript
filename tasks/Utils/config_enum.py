# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from enum import Enum

class ShikigamiClass(str, Enum):
    UR = 'UR'
    SP = 'SP'
    SSR = 'SSR'
    SR = 'SR'
    R = 'R'
    N = 'N'
    # 材料
    MATERIAL = 'MATERIAL'


class DemonClass(str, Enum):
    # tsuchigumo 土蜘蛛
    TSUCHIGUMO = '土蜘蛛'
    # oboroguruma 胧车
    OBOROGURUMA = '胧车'
    # odokuro 荒骷髅
    ODOKURO = '荒骷髅'
    # namazu 地震鲇
    NAMAZU = '地震鲇'
    # shinkiro 蜃气楼
    SHINKIRO = '蜃气楼'
    # ghostly songstress 鬼灵歌伎
    GHOSTLY_SONGSTRESS = '鬼灵歌伎'
    # Boss_7 夜荒魂
    BOSS_7 = '夜荒魂'
    # Boss_8 八咫镜
    BOSS_8 = '八咫镜'
    # Boss_9 天羽羽斩
    BOSS_9 = '天羽羽斩'
    # Boss_10 预言星盘
    BOSS_10 = '预言星盘'
    # Boss_11 月之石
    BOSS_11 = '月之石'
    # Boss_12 纺缘锤
    BOSS_12 = '纺缘锤'
    # Boss_13 稻荷穗箭
    BOSS_13 = '稻荷穗箭'






