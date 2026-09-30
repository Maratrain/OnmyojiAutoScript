# This Python file uses the following encoding: utf-8
import re

from module.logger import logger

# 与旧版 Dashen 策略共用的大神 UP 主 UID 列表，已去重，供加权投票策略使用。
DASHEN_UIDS = ["462382f1127b46c5add1185d88f0ea40","54399446d5084a0e8878dac8f6ff56d0","840742d60e4a43208605ae68ca8c3f64","c3c989fae4074d04b478b8ba47ae4120","aaa923436aa440df9ac1ee3f47387b99","72584a679e2f45b6859566b5523400d5","3d4726d99f2642a485729695b798cb8c","1d2dcbbd7e3d481c8d0f27ba4ff0dc71","21657a558bdd4ddfb6501298350336e7","0e4e0c5a1e494a1fa9a58ac55de689c1","30e383c884f844a18a7a76fe3c1e888f","d9dc2a75497c4a91b2db1e909a36544d","e7107cd3010e418da26672669d8eeb5e","74adeb1bfb2b4cf382edbbb430da2149","e87f855f36f24b34b9d8f8a4fb2d62b2","82de68c7672e4b6da65493fb829b57b6","f6d6bb15d6024200a985752e2ab4c373","06e2bba14a914012bc8064601cfa19ea","8982241de1844638b4bb455139b8dcc0","a9724e98c1cb4a4e931ebc3f467ea73d","e9b0a16325af46628e8dfb9e7942cf1d","b6b5bc8277e34f69aeca018db0081397","74db771d92a54c28ae3e98d19aa565a3","e498e524252041e29999b38e57c4df1d","30b0c2923faa483f95572c324a5bc910","e32aedbdd8da46a5b5b497a16c4b7658"]

# 已知博主昵称到 UID 的映射，供跟单策略用昵称配置优先级列表。
DASHEN_BLOGGERS = {
    '面灵气喵': '462382f1127b46c5add1185d88f0ea40',
    '余岁岁': '54399446d5084a0e8878dac8f6ff56d0',
    '七面相': '840742d60e4a43208605ae68ca8c3f64',
    '待机中的徐ok': 'c3c989fae4074d04b478b8ba47ae4120',
    '雯雯': 'aaa923436aa440df9ac1ee3f47387b99',
    '晨时微凉': '72584a679e2f45b6859566b5523400d5',
    '梅布斯尼': '3d4726d99f2642a485729695b798cb8c',
    '鸽海成路': '1d2dcbbd7e3d481c8d0f27ba4ff0dc71',
    '徐清林': '21657a558bdd4ddfb6501298350336e7',
    '不包邮哦亲': '0e4e0c5a1e494a1fa9a58ac55de689c1',
    '天真珈百璃': '30e383c884f844a18a7a76fe3c1e888f',
    '薛定谔家查查尔': 'd9dc2a75497c4a91b2db1e909a36544d',
    '嘤嘤井': 'e7107cd3010e418da26672669d8eeb5e',
    'Prince班崎': '74adeb1bfb2b4cf382edbbb430da2149',
    '靠脸混饭': 'e87f855f36f24b34b9d8f8a4fb2d62b2',
    '夜神月丶L': '82de68c7672e4b6da65493fb829b57b6',
    '是大荣啦': 'f6d6bb15d6024200a985752e2ab4c373',
    '炒饭菌': '06e2bba14a914012bc8064601cfa19ea',
    '清流不加班': '8982241de1844638b4bb455139b8dcc0',
    '槐夏三十': 'a9724e98c1cb4a4e931ebc3f467ea73d',
    '落沫颜': 'e9b0a16325af46628e8dfb9e7942cf1d',
    'Mico林木森': 'b6b5bc8277e34f69aeca018db0081397',
    '查查尔': 'd9dc2a75497c4a91b2db1e909a36544d',
    'CC南浔': '74db771d92a54c28ae3e98d19aa565a3',
    '冰七喜Den': 'e498e524252041e29999b38e57c4df1d',
    '行水姑娘': '30b0c2923faa483f95572c324a5bc910',
    '更慕林': 'e32aedbdd8da46a5b5b497a16c4b7658',
}

_HEX_UID = re.compile(r'^[0-9a-fA-F]{32}$')


def resolve_follow_list(raw):
    """把跟单配置解析为有序去重的 UID 列表，从左到右即优先级从高到低。

    每一段可填大神昵称或 32 位 UID，用逗号/顿号/空白分隔；
    无法识别的段只告警跳过，全部无法识别时返回空列表由调用方报错。
    """
    uids = []
    for token in re.split(r'[,，、\s]+', (raw or '').strip()):
        if not token:
            continue
        if _HEX_UID.match(token):
            uid = token.lower()
        elif token in DASHEN_BLOGGERS:
            uid = DASHEN_BLOGGERS[token]
        else:
            logger.warning(f'[对弈竞猜-跟单] 无法识别的跟单博主，已跳过: {token}')
            continue
        if uid not in uids:
            uids.append(uid)
    return uids

