# This Python file uses the following encoding: utf-8

"""百鬼棋局阵容羁绊注册表。

新增体系时：
1. 以羁绊拼音创建独立策略 Python 文件；
2. 在 ``LINEUP_REGISTRY`` 注册拼音键、中文显示名和策略对象。

OASX 下拉选项和主任务运行时选择均由本注册表生成。
"""

from enum import Enum
import random

from tasks.Chess.strategy.lineup_strategy import (
    ARAKAWA,
    DAJIANGSHAN,
    HAIGUO,
    HUYAO,
    MINGFU,
    QIJIAOSHAN,
    LIUHUO,
)


LINEUP_REGISTRY = {
    'qijiaoshan': {
        'display_name': '七角山',
        'strategy': QIJIAOSHAN,
    },
    'haiguo': {
        'display_name': '海国',
        'strategy': HAIGUO,
    },
    'dajiangshan': {
        'display_name': '大江山',
        'strategy': DAJIANGSHAN,
    },
    'huyao': {
        'display_name': '狐妖',
        'strategy': HUYAO,
    },
    'mingfu': {
        'display_name': '冥府',
        'strategy': MINGFU,
    },
    'liuhuo': {
        'display_name': '流火',
        'strategy': LIUHUO,
    },
    'arakawa': {
        'display_name': '荒川',
        'strategy': ARAKAWA,
    },
}

DEFAULT_LINEUP_KEY = 'qijiaoshan'

# “随机”不是一套具体阵容，只出现在配置下拉框中；运行时每局从
# LINEUP_REGISTRY 里抽取一套真实阵容。注册表本身不收录该键。
RANDOM_LINEUP_KEY = 'random'
RANDOM_LINEUP_DISPLAY = '随机'

# 枚举值使用中文，使 OASX 下拉框直接显示中文；运行时通过下面的解析
# 函数还原成稳定的拼音键。
LineupBond = Enum(
    'LineupBond',
    {
        'RANDOM': RANDOM_LINEUP_DISPLAY,
        **{
            key.upper(): entry['display_name']
            for key, entry in LINEUP_REGISTRY.items()
        },
    },
    type=str,
)


def resolve_lineup_key(value) -> str:
    """将拼音键、中文显示名或 OASX 枚举值统一解析为拼音键。

    “随机”原样返回 RANDOM_LINEUP_KEY，由调用方决定抽取时机。
    """
    raw = getattr(value, 'value', value)
    raw = str(raw or '').strip()
    if raw in (RANDOM_LINEUP_KEY, RANDOM_LINEUP_DISPLAY):
        return RANDOM_LINEUP_KEY
    if raw in LINEUP_REGISTRY:
        return raw
    for key, entry in LINEUP_REGISTRY.items():
        if raw == entry['display_name']:
            return key
    return DEFAULT_LINEUP_KEY


def pick_random_lineup_key() -> str:
    """从已注册的真实阵容中随机抽取一套。"""
    return random.choice(list(LINEUP_REGISTRY.keys()))
