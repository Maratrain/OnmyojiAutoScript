# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import copy
from time import sleep

import difflib
from datetime import time, datetime, timedelta
from module.atom.image import RuleImage
from ppocronnx.predict_system import BoxedResult

from tasks.Component.config_base import Time
from tasks.DailyTrifles.page import page_store_gift_room, page_friends_luck, page_guild_wish

from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.assets import GameUiAssets
from tasks.GameUi.page import page_main, page_summon, page_guild, page_mall, page_friends, page_courtyard_affairs, page_mall_recommend
from tasks.DailyTrifles.config import DailyTriflesConfig, IncomeSnapshot
from tasks.DailyTrifles.assets import DailyTriflesAssets
from tasks.Component.Summon.summon import Summon

from tasks.GlobalGame.assets import GlobalGameAssets

from module.atom.ocr import RuleOcr
from module.logger import logger
from module.exception import TaskEnd
from module.base.timer import Timer
from decimal import Decimal
from module.log_income import (
    INCOME_FIELDS as INCOME_LOG_FIELDS,
    INCOME_LOG_PREFIX,
    find_income_baseline,
    write_income_day,
)
from tasks.DailyTrifles.config import SummonType
import re
from typing import Any, Optional, List, Callable


# 统计每日收益的资源：(中文名, 资产名, 上限)
# 前三个在庭院，中间四个在秘卷屋，最后一个在商城热门推荐页。
# 字段顺序以 module.log_income.INCOME_FIELDS 为准，这里只补中文名和资产。
INCOME_ITEMS = {
    'gold': ('金币', 'O_INCOME_GOLD', 10 ** 11),
    'jade': ('勾玉', 'O_INCOME_JADE', 10 ** 8),
    'ap': ('体力', 'O_INCOME_AP', 10 ** 6),
    'sca_orochi_scales': ('八岐大蛇鳞片', 'O_INCOME_SCA_OROCHI_SCALES', 10 ** 7),
    'sca_reverse_scale': ('大蛇的逆鳞', 'O_INCOME_SCA_REVERSE_SCALE', 10 ** 7),
    'sca_demon_souls': ('逢魔之魂', 'O_INCOME_SCA_DEMON_SOULS', 10 ** 7),
    'sca_picture_book': ('被遗忘的绘本', 'O_INCOME_SCA_PICTURE_BOOK', 10 ** 7),
    'mystery_amulet': ('神秘的符咒', 'O_INCOME_MYSTERY_AMULET', 10 ** 7),
}
# 名字对不上会直接 KeyError，比静默少统计一项好
INCOME_FIELDS = tuple((name, *INCOME_ITEMS[name]) for name in INCOME_LOG_FIELDS)
# 按读取位置分组：庭院顶栏 / 秘卷屋 / 商城热门推荐页
INCOME_MAIN = tuple((name, *INCOME_ITEMS[name]) for name in ('gold', 'jade', 'ap'))
INCOME_SCALES = tuple((name, *INCOME_ITEMS[name]) for name in (
    'sca_orochi_scales',
    'sca_reverse_scale',
    'sca_demon_souls',
    'sca_picture_book',
))
INCOME_MALL = tuple((name, *INCOME_ITEMS[name]) for name in ('mystery_amulet',))
# 三组必须正好覆盖全部字段；漏一组或重一个，导入的时候就炸，不要等到跑任务
assert {item[0] for item in INCOME_MAIN + INCOME_SCALES + INCOME_MALL} == set(INCOME_LOG_FIELDS)

INCOME_UNITS = {'': 1, '千': 1000, '万': 10000, '亿': 100000000}
INCOME_NUMBER = re.compile(r'(\d+(?:\.\d+)?)([千万亿]?)')


def parse_income_number(text: str) -> Optional[int]:
    """解析顶栏数字，支持 "1234"、"1.2万"、"6.33亿"、"5000/5000"。

    判不准一律返回 None。OCR 把「万」认成「方/力」时会连单位一起滤掉，
    1.2万 就变成 1.2 再被截成 1，差四个数量级；这种错值比没有值更糟。
    """
    text = text.replace(' ', '').replace(',', '').replace('，', '')
    for old, new in (('I', '1'), ('D', '0'), ('S', '5'), ('B', '8'),
                     ('？', '2'), ('d', '6'), ('o', '0'), ('O', '0')):
        text = text.replace(old, new)
    # 体力之类的会写成 A/B，只取斜杠前面
    tokens = INCOME_NUMBER.findall(text.split('/')[0])
    if len(tokens) != 1:
        return None
    number, unit = tokens[0]
    if '.' in number and not unit:
        return None
    return int(Decimal(number) * INCOME_UNITS[unit])


class ScriptTask(GameUi, Summon, DailyTriflesAssets):

    def run(self):
        con = self.config.daily_trifles.trifles_config
        # 每日召唤
        if con.one_summon:
            self.run_one_summon()
        if con.courtyard_affairs:
            self.run_courtyard_affairs()
        if con.pickup_email:
            self.run_pickup_email()
        if self.config.daily_trifles.guild_donate.enable:
            self.run_guild_donate()
        # 吉闻
        if con.luck_msg:
            self.run_luck_msg()
        # 好友点赞
        if self.config.daily_trifles.friend_like.enable:
            self.run_friend_like()
        # 商店签到 or 购买寿司
        if con.store_sign or con.buy_sushi_count > 0:
            self.run_store()
        # 统计每日收益
        if con.income_stat:
            self.run_income_stat()
        self.config.save()
        self.plan_next_dt()
        raise TaskEnd('DailyTrifles')

    def run_income_stat(self):
        """统计每日收益：庭院资源、商城符咒、秘卷屋鳞片各记一次快照"""
        logger.hr('统计每日收益', 2)
        # 放在函数内导入，和 run_buy_sushi 保持一致，避免任务模块互相牵连
        from tasks.RichMan.assets import RichManAssets

        snapshot = IncomeSnapshot(dt=datetime.now())
        self.goto_page(page_main)
        self.read_income_group(snapshot, INCOME_MAIN)

        # 符咒在商城的「热门推荐」页读，不必再跑一趟召唤页
        self.goto_page(page_mall_recommend, confirm_wait=2.5)
        self.read_income_group(snapshot, INCOME_MALL)

        self.goto_page(page_mall)
        if self.ui_click_until_appear_or_timeout(
                RichManAssets.I_MALL_SCCALES, RichManAssets.I_MALL_SCCALES_CHECK,
                interval=1, timeout=10):
            self.read_income_group(snapshot, INCOME_SCALES)
            # 秘卷屋不是注册页面，先退回商城再交给导航
            self.ui_click_until_appear_or_timeout(
                GlobalGameAssets.I_UI_BACK_YELLOW, self.I_CHECK_MALL, interval=1, timeout=10)
        else:
            logger.warning('[收益] 未能进入秘卷屋，跳过鳞片类四项')

        self.goto_page(page_main)
        self.record_income(snapshot)

    def read_income_group(self, snapshot: IncomeSnapshot, fields: tuple):
        for field, name, asset, upper in fields:
            value = self.read_income(name, getattr(self, asset), upper)
            setattr(snapshot, field, value)

    def read_income(self, name: str, rule: RuleOcr, upper: int) -> int:
        """读一次顶栏数字，读不出或者超出合理范围就返回 -1 留给下一次运行"""
        self.screenshot()
        # 走文本检测 + 识别，和标注工具的测试按钮同一条路径
        # （Single/Digit 的 ocr() 只做识别，ROI 里带图标时会读出「路421+」）
        text = rule.detect_text(self.device.image)
        value = parse_income_number(text)
        if value is None or not 0 <= value <= upper:
            logger.warning(f'[收益] {name}: 放弃本次识别, 原文 [{text}]')
            return -1
        logger.info(f'[收益] {name}: {value}')
        return value

    def record_income(self, snapshot: IncomeSnapshot):
        """快照写进日志（人可读）和日汇总（长期保留），再拿上一个有记录的日子做差"""
        logger.info(INCOME_LOG_PREFIX + ' '.join(
            f'{field}={getattr(snapshot, field)}' for field, _, _, _ in INCOME_FIELDS))

        # 日汇总不受日志 7 天清理影响，是收益历史的正主；日志那行只作兜底
        day = snapshot.dt.date()
        write_income_day(self.config.config_name, day, {
            'dt': snapshot.dt.strftime('%Y-%m-%d %H:%M:%S'),
            'values': {field: int(getattr(snapshot, field)) for field in INCOME_LOG_FIELDS},
        })

        baseline = find_income_baseline(self.config.config_name, day)
        if baseline is None:
            logger.info('[收益] 今天之前没有记录，跳过做差')
            return
        baseline_day, previous = baseline
        logger.hr('今日收益', 2)
        logger.info(f'[收益] 对比基准日: {baseline_day}')
        for field, name, _, _ in INCOME_FIELDS:
            now, before = getattr(snapshot, field), previous['values'].get(field, -1)
            if now < 0 or before < 0:
                logger.warning(f'[收益] {name}: 不完整，跳过做差, {before} -> {now}')
                continue
            logger.info(f'[收益] {name}: {before} -> {now} ({now - before:+d})')

    def run_one_summon(self):
        logger.hr('每日召唤', 2)
        if self.config.daily_trifles.today_is_done('summon'):
            logger.info('[每日琐事] 今日已完成，跳过')
            return
        self.goto_page(page_summon)
        config = self.config.daily_trifles.trifles_config
        if config.summon_type == SummonType.default:
            self.summon_one(draw_mystery_pattern=config.draw_mystery_pattern)
            self.check_time()
        elif config.summon_type == SummonType.recall:
            self.summon_recall()
        self.back_summon_main()
        self.config.daily_trifles.done_record.summon_dt = datetime.now()

    def check_time(self):
        config = self.config.daily_trifles.trifles_config
        now = datetime.now()
        next_run = now + self.config.daily_trifles.scheduler.success_interval
        # 检查是否跨月（next_run的月份与当前月份不同）
        if next_run.month != now.month:
            # 跨月重置神秘图案触发状态
            if not config.draw_mystery_pattern:
                config.draw_mystery_pattern = True
                logger.info(
                    f"[每日琐事] 重置 draw_mystery_pattern 为 True，下次运行: {next_run}")
        else:
            # 如果还是在同一月份，则没必要再绘制神秘图案
            config.draw_mystery_pattern = False
        self.config.save()

    def summon_recall(self):
        """
        确保在召唤界面,每日召唤一次
        召唤结束后回到 召唤主界面
        :return:
        """
        list = [self.O_SELECT_SM2, self.O_SELECT_SM3, self.O_SELECT_SM4]
        count = 0
        while True:
            count += 1

            for i in range(len(list)):
                sleep(1)
                self.goto_page(page_summon)
                self.appear_then_click(self.I_UI_BACK_RED, interval=1)
                x, y = list[i].coord()
                self.device.click(x, y)
                sleep(1)
                self.screenshot()
                if self.appear(self.I_RECALL_TICKET):
                    break
                logger.info("[每日琐事] 尝试选择今忆召唤分组")

            self.screenshot()
            if self.appear(self.I_RECALL_TICKET):
                break
            if count >= 3:
                self.config.notifier.push(title='今忆召唤抽卡失败', content='每日任务,今忆召唤抽卡失败!!!')
                return

        logger.info('[每日琐事] 开始今忆召唤')
        self.wait_until_appear(self.I_RECALL_TICKET)
        while True:
            ticket_info = self.O_RECALL_TICKET_AREA.ocr(self.device.image)
            # 处理 None 和空字符串
            if ticket_info is None or ticket_info == '':
                ticket_info = 0
            else:
                # 使用正则表达式提取字符串中的数字
                match = re.search(r'\d+', ticket_info)
                if match:
                    ticket_info = int(match.group())
                else:
                    logger.warning(f'[每日琐事] 无效的票数识别结果: {ticket_info}，应为数字字符串')
                    ticket_info = 0  # 将无效值设置为默认值 0
            if ticket_info <= 0:
                logger.warning('[每日琐事] 没有今忆召唤票')
                return
            # 某些情况下滑动异常
            self.S_RANDOM_SWIPE_1.name = 'S_RANDOM_SWIPE'
            self.S_RANDOM_SWIPE_2.name = 'S_RANDOM_SWIPE'
            self.S_RANDOM_SWIPE_3.name = 'S_RANDOM_SWIPE'
            self.S_RANDOM_SWIPE_4.name = 'S_RANDOM_SWIPE'
            while 1:
                self.screenshot()
                if self.appear(self.I_RECALL_ONE_TICKET):
                    break
                if self.appear_then_click(self.I_RECALL_TICKET, interval=1):
                    continue

            # 画一张票
            sleep(1)
            while 1:
                self.screenshot()
                if self.appear(self.I_RECALL_SM_CONFIRM, interval=0.6):
                    self.ui_click_until_disappear(self.I_RECALL_SM_CONFIRM)
                    break
                if self.appear(self.I_SM_CONFIRM_2, interval=0.6):
                    self.ui_click_until_disappear(self.I_SM_CONFIRM_2)
                    break
                if self.appear(self.I_RECALL_ONE_TICKET, interval=1):
                    # 某些时候会点击到 “语言召唤”
                    if self.appear_then_click(self.I_UI_CANCEL, interval=0.8):
                        continue
                    self.summon()
                    continue
            logger.info('[每日琐事] 单次召唤成功')

    def run_guild_donate(self):
        logger.hr('阴阳寮捐赠', 2)
        if self.config.daily_trifles.today_is_done('guild_donate'):
            logger.info('[每日琐事] 今日已完成，跳过')
            return
        self.goto_page(page_guild_wish)
        timeout_timer = Timer(2).start()
        while not timeout_timer.reached():
            self.screenshot()
            if self.appear(self.I_DT_GW_THANKS):
                self.ui_click(self.I_DT_GW_THANKS, self.I_DT_GW_THANKED, interval=0.8)
                timeout_timer.reset()
                continue
        self.appear_then_click(self.I_UI_BACK_RED)
        donate_datas: list = [
            (self.config.daily_trifles.guild_donate.guild_member_list_v,
             lambda : self.switch_select(self.I_DT_GW_GUILD_MEMBER_SELECTED, self.I_DT_GW_FRIEND_SELECTED, self.I_DT_GW_SELECT_GUILD_MEMBER),
             self.config.daily_trifles.guild_donate.name_check),
            (self.config.daily_trifles.guild_donate.friend_list_v,
             lambda : self.switch_select(self.I_DT_GW_FRIEND_SELECTED, self.I_DT_GW_GUILD_MEMBER_SELECTED, self.I_DT_GW_SELECT_FRIEND),
             self.config.daily_trifles.guild_donate.name_check)
        ]
        all_done = True
        for name_list, switch_func, name_check in donate_datas:
            # 分别执行两个名单，前一个名单失败也不能跳过后一个名单。
            donate_ret = self.donate(name_list, switch_func, name_check)
            all_done = all_done and donate_ret
        if self.config.daily_trifles.guild_donate.auto_get_rewards:
            self.guild_donate_get_reward()
        self.config.daily_trifles.done_record.guild_donate_finish = all_done
        self.goto_page(page_main)

    def guild_donate_get_reward(self):
        """领取捐赠碎片的奖励"""
        timeout_timer = Timer(3).start()
        has_reward = False
        while not timeout_timer.reached():
            self.screenshot()
            if self.appear(self.I_UI_BACK_RED, interval=0.6):
                break
            if self.appear(self.I_DT_GW_DONATE_RECORD_RED):
                self.ui_click(self.I_DT_GW_DONATE_RECORD, self.I_UI_BACK_RED, interval=1.2)
                has_reward = True
                continue
        if not has_reward:
            logger.info('[每日琐事] 没有可领取的奖励，退出')
            return
        timeout_timer.reset()
        while not timeout_timer.reached():
            self.screenshot()
            self.ui_reward_appear_click()
            if self.click_ui_confirm(interval=0.6):
                continue
            if self.appear_then_click(self.I_DT_GW_DONATE_RECORD_THANKS, interval=1.5):  # 受赠界面的一键感谢
                timeout_timer.reset()
                continue
            if self.appear(self.I_DT_GW_DONATE_RED, interval=2.5):  # 赠予界面的一键领取
                self.ui_click(self.I_DT_GW_GIVE, self.I_DT_GW_ONE_COLLECT)
                self.appear_then_click(self.I_DT_GW_ONE_COLLECT, interval=0.6)
                timeout_timer.reset()
                continue
        self.ui_click_until_disappear(self.I_UI_BACK_RED)

    def donate(self, name_list: List[str], switch_func: Callable, name_check: bool) -> bool:
        """执行碎片捐赠流程

        :param name_list: 待捐赠碎皮的名称列表
        :param switch_func: 切换好友/阴阳寮/...的方法
        :param name_check: 是否使用ocr检查用户名
        :return: 是否全部捐赠成功 (出现检索名称后为空或者碎皮不足都是False, 仅全部捐成功才是True)
        """
        all_done = True
        for name in name_list:
            switch_func()
            self.swipe(self.S_DT_GW_OPEN_SEARCH, interval=1.2)  # 向下滑动拉出搜索框
            # 从按照交换搜索切换到按名称搜索
            self.switch_select(self.I_DT_GW_SEARCH_BY_NAME, self.I_DT_GW_SEARCH_BY_SWAP, self.I_DT_GW_SELECT_BY_NAME)
            self.appear_then_click(self.I_DT_GW_CLEAR_SEARCH)  # 清除搜索框内容
            self.ui_click(self.C_DT_GW_INPUT_SEARCH, self.I_DT_GW_CONFIRM, interval=1.5)  # 点击搜索框
            self.click(self.C_DT_GW_CLICK_INPUT)  # 点击名称输入框
            # uiautomator2 通过 FastInputIME 传输 UTF-8 文本，并在必要时回退到 set_text
            logger.info(f'[每日琐事] 使用 uiautomator2 输入名称: {name}，等待输入完成')
            self.device.u2.send_keys(name, clear=True)
            self.ui_click_until_disappear(self.I_DT_GW_CONFIRM, interval=1.5)  # 点击确定
            donate_btn = self.I_DT_GW_DONATE
            if name_check:  # 若有多个相同前缀名称, 则需要取出一样的或最相近的名称
                name_roi = self.find_target_name(name)
                if name_roi is None:
                    logger.warning(f'[每日琐事] {name} 校验失败，可能未祈愿或未找到')
                    all_done = False
                    continue
                # 设置赠与按钮back与对应name同一行
                donate_btn.roi_back = [name_roi[0]-5, name_roi[1] - 15, 850, 90]  # 设置赠与按钮back区域和对应name同一行
            self.I_DT_GW_FULL.roi_back = donate_btn.roi_back  # 设置已捐满标志back区域和赠与按钮同一行
            self.I_DT_GW_INSUFFICIENT.roi_back = donate_btn.roi_back  # 设置碎片不足标志back区域和赠与按钮同一行
            donate_ret = self.process_donate(donate_btn, name)
            all_done = all_done and donate_ret  # 有一次没成功则all_done永远False
        return all_done

    def process_donate(self, donate_btn: RuleImage, name: str) -> bool:
        """捐赠式神碎片
        TODO: 游戏有bug,搜索结束之后会突然神经展开全部寮友/好友,会有一瞬间识别到了好友,点击捐赠结果实际捐错人了

        :param name: 被捐方名称
        :param donate_btn: 赠与按钮
        :return: 捐赠是否成功(点击了捐赠/确定/识别到已满都认为成功)
        """
        timeout_timer = Timer(3).start()
        donated = False  # 判断是否已执行捐赠
        while not timeout_timer.reached():
            self.screenshot()
            if self.appear(self.I_DT_GW_SEARCH_EMPTY):
                logger.warning('[每日琐事] 可能未祈愿或未找到，跳过')
                if self.config.daily_trifles.guild_donate.notify_enable:
                    self.config.notifier.push(title='好友搜索失败', content=f'{name} 搜索失败, 没有搜索到对应用户, 无法捐赠')
                return False
            if not donated and self.appear_then_click(donate_btn, interval=2.5):
                timeout_timer.reset()
                # 点击后，等待所有弹窗消失（确认、奖励），然后重新定位
                post_click_timeout = Timer(3).start()
                while not post_click_timeout.reached():
                    self.screenshot()
                    # 处理确认弹窗（新旧两套 UI 哪个出现就点哪个）
                    confirm = self.match_ui_confirm(interval=0.6)
                    if confirm is not None:
                        self.ui_get_reward(confirm, click_interval=1.5)
                        donated = True
                    # 如果没有弹窗了，退出子循环
                    if not self.appear(self.I_UI_REWARD) and not self.appear(self.I_UI_REWARD):
                        break
                if donated:
                    # 处理了弹窗，视为捐赠成功
                    logger.info(f'[每日琐事] 捐赠 {name} 成功')
                    return True
                else:
                    # 子循环结束后，重新定位目标行（因为如果被搜索到的玩家有多个，被赠与方被赠送满了就会下沉到最后位置）
                    new_roi = self.find_target_name(name)
                    if new_roi is None:
                        logger.warning(f'[每日琐事] {name} 捐赠后已消失，跳过')
                        return False
                    # 更新三个按钮的 ROI
                    new_roi_back = [new_roi[0] - 5, new_roi[1] - 15, 850, 90]
                    donate_btn.roi_back = new_roi_back
                    self.I_DT_GW_FULL.roi_back = new_roi_back
                    self.I_DT_GW_INSUFFICIENT.roi_back = new_roi_back
                    logger.info(f"[每日琐事] 捐赠尝试后更新 ROI: {new_roi_back}")
                    continue

            if self.appear(self.I_DT_GW_INSUFFICIENT, interval=0.6):
                logger.warning('[每日琐事] 碎片不足，无法捐赠，跳过')
                if self.config.daily_trifles.guild_donate.notify_enable:
                    self.config.notifier.push(title='捐赠碎片不足', content=f'捐给{name}的碎片不足, 请上线查看')
                return False
            if self.appear(self.I_DT_GW_FULL, interval=0.6):
                logger.info(f'[每日琐事] 捐赠成功')
                donated = True
        return donated

    def find_target_name(self, name) -> List[int]:
        """寻找目标名称
        :param name: 名称
        :return: [x, y, w, h]
        """
        timeout_timer = Timer(3).start()
        name_roi: List[int] = None
        # TODO: 这里只找了第一页, 若相似名称过多后续需要添加翻页继续找功能
        while not timeout_timer.reached():
            self.screenshot()
            if self.appear(self.I_DT_GW_SEARCH_EMPTY):  # 空的直接退出
                if self.config.daily_trifles.guild_donate.notify_enable:
                    self.config.notifier.push(title='好友搜索失败', content=f'没有搜索到对应用户 {name}, 无法捐赠')
                return None
            text_results = self.O_DT_GW_NAME.detect_and_ocr(self.device.image)
            mx_similarity = 0.5
            for result in text_results:
                if result.ocr_text == name:
                    return self.extract_roi(result)  # 名称一模一样则直接返回
                similarity = difflib.SequenceMatcher(None, result.ocr_text, name).ratio()
                if similarity > mx_similarity:
                    mx_similarity = similarity
                    name_roi = self.extract_roi(result)
            if name_roi is None:
                continue
            return name_roi  # 找到了直接退出
        return name_roi

    def extract_roi(self, result: BoxedResult) -> list[int]:
        """从ocr结果提取对应的roi坐标"""
        x = self.O_DT_GW_NAME.roi[0] + result.box[0, 0]
        y = self.O_DT_GW_NAME.roi[1] + result.box[0, 1]
        w, h = result.box[1, 0] - result.box[0, 0], result.box[2, 1] - result.box[0, 1]
        return [x, y, w, h]

    def switch_select(self, target: RuleImage, other: RuleImage, select: RuleImage):
        """切换选中的元素"""
        while True:
            self.screenshot()
            if self.appear(target):
                break
            if self.appear_then_click(select, interval=0.6):
                continue
            if self.appear_then_click(other, interval=1.8):
                continue

    def run_luck_msg(self):
        logger.hr('吉闻', 2)
        if self.config.daily_trifles.today_is_done('luck_msg'):
            logger.info('[每日琐事] 今日已完成，跳过')
            return
        self.goto_page(page_friends_luck)
        logger.info('[每日琐事] 开始处理吉闻')
        check_timer = Timer(2)
        check_timer.start()
        while 1:
            self.screenshot()

            if self.appear_then_click(self.I_CLICK_BLESS, interval=1):
                continue
            if self.appear_then_click(self.I_ONE_CLICK_BLESS, interval=1):
                continue
            if self.ui_reward_appear_click():
                logger.info('[每日琐事] 领取吉闻奖励')
                break
            if check_timer.reached():
                logger.warning('[每日琐事] 没有吉闻消息')
                break

        self.goto_page(page_main)
        self.config.daily_trifles.done_record.luck_msg_dt = datetime.now()

    def run_friend_like(self):
        """好友点赞: 按名单精准点赞或点赞全部好友, 每号每日 20 次上限由游戏控制"""
        logger.hr('好友点赞', 2)
        if self.config.daily_trifles.today_is_done('friend_like'):
            logger.info('[每日琐事] 今日已完成，跳过')
            return
        cfg = self.config.daily_trifles.friend_like
        names = cfg.like_names_v
        search_targets = cfg.search_names_v
        if not names and not search_targets and not cfg.like_all:
            logger.info('[点赞] 名单为空且未开启全部点赞，跳过')
            return
        liked = 0
        if self._goto_friend_page():
            for name, server in names:
                if liked >= 20:
                    logger.info('[点赞] 已达 20 次上限，停止')
                    break
                if self._like_friend_by_name(name, server, cfg.name_check):
                    liked += 1
            if search_targets and liked < 20:
                if self._open_add_page():
                    # 规定: 搜索点赞固定使用全服
                    self._ensure_search_server()
                    for target in search_targets:
                        if liked >= 20:
                            logger.info('[点赞] 已达 20 次上限，停止')
                            break
                        if self._like_by_search(target, cfg.name_check):
                            liked += 1
            if not names and not search_targets and cfg.like_all:
                liked = self._like_all_friends()
        logger.info(f'[点赞] 本次点赞 {liked} 人')
        self.config.daily_trifles.done_record.friend_like_dt = datetime.now()
        self._close_friend_page()

    def _close_friend_page(self):
        """关闭好友界面回庭院; 不走 goto_page, 缘初新手庭院下 I_CHECK_MAIN 判定不可用"""
        timer = Timer(10).start()
        while not timer.reached():
            self.screenshot()
            if not self.appear(GameUiAssets.I_CHECK_FRIENDS, interval=0.5):
                return
            self.appear_then_click(GlobalGameAssets.I_UI_BACK_RED, interval=1)

    def _goto_friend_page(self) -> bool:
        """进入好友界面: 庭院卷轴菜单→好友按钮, 已在好友页直接返回"""
        logger.info('[点赞] 正在进入好友界面')
        timer = Timer(40).start()
        while not timer.reached():
            self.screenshot()
            if self.appear(GameUiAssets.I_CHECK_FRIENDS, interval=0.5):
                return True
            if self.appear_then_click(GlobalGameAssets.I_UI_BACK_RED, interval=1):
                continue
            # 点卷轴切换底栏展开态, 再点好友按钮; 底栏未展开时该坐标落空无害
            self.click(self.C_FL_SCROLL)
            sleep(1.2)
            self.click(self.C_FL_GOTO_FRIENDS)
            sleep(1.5)
        logger.warning('[点赞] 进入好友界面超时')
        return False

    def _expand_group(self, cross: bool) -> bool:
        """展开好友/跨区好友分组(手风琴式, 展开其一另一分组自动收起)

        :param cross: False 好友分组, True 跨区好友分组
        """
        unfold = self.I_FL_GROUP_UNFOLD
        for _ in range(6):
            self.screenshot()
            if cross:
                # 跨区分组展开时栏在第二栏(y≈205); 好友分组展开时跨区栏被推到下方(y≈592)
                unfold.roi_back = (390, 190, 120, 55)
                if self.appear(unfold):
                    return True
                self.click(self.C_FL_BAR_CROSS)
            else:
                unfold.roi_back = (390, 150, 120, 50)
                if self.appear(unfold):
                    return True
                self.click(self.C_FL_BAR_FRIEND)
            sleep(1.5)
        logger.warning(f'[点赞] 展开{"跨区好友" if cross else "好友"}分组超时')
        return False

    def _like_friend_by_name(self, name: str, server: str, name_check: bool) -> bool:
        """找到指定好友, 打开聊天面板核对后点赞

        :param server: 目标区服名(聊天面板右上角紫色文字), 空串表示不校验区服;
                       同名好友会逐个候选尝试, 直到名字与区服都核对通过
        """
        tried: set = set()
        for cross in (False, True):
            if not self._expand_group(cross):
                continue
            while True:
                row = self._scan_list_for_name(name, tried)
                if row is None:
                    break
                tried.add(row)
                self.device.click(*row)
                # 等聊天面板切换完成, 避免已点赞判定读到上一位好友的拇指
                sleep(0.8)
                if name_check and not self._wait_chat_name(name):
                    logger.warning(f'[点赞] {name} 聊天面板名字核对失败，跳过该候选')
                    continue
                if server and self._wait_chat_server(server) is None:
                    logger.warning(f'[点赞] {name} 区服核对失败(目标 {server})，跳过该候选')
                    continue
                return self._click_thumb(name)
        target = f'{name}@{server}' if server else name
        logger.warning(f'[点赞] 未在好友列表中找到 {target}')
        return False

    def _scan_list_for_name(self, name: str, tried: Optional[set] = None) -> Optional[tuple]:
        """在当前展开分组的列表中滚动查找名字, 返回该行点击坐标; tried 中的行视为已核对过"""
        last_texts: Optional[set] = None
        for _ in range(12):
            self.screenshot()
            results = self.O_FL_LIST_NAME.detect_and_ocr(self.device.image)
            texts = set()
            skipped = False
            for r in results:
                text = r.ocr_text.strip()
                if not text:
                    continue
                texts.add(text)
                if text == name or difflib.SequenceMatcher(None, text, name).ratio() >= 0.75:
                    x = self.O_FL_LIST_NAME.roi[0] + r.box[0, 0]
                    y = self.O_FL_LIST_NAME.roi[1] + r.box[0, 1]
                    w = r.box[1, 0] - r.box[0, 0]
                    h = r.box[2, 1] - r.box[0, 1]
                    coord = (int(x + w / 2), int(y + h / 2))
                    if tried and self._row_tried(tried, coord):
                        skipped = True
                        continue
                    return coord
            # 连续两屏内容相同视为翻到列表底; 跳过已试行时需继续翻页找下一个同名候选
            if not skipped and last_texts is not None and texts == last_texts:
                return None
            last_texts = texts
            self.swipe(self.S_FL_LIST_UP, interval=1.2)
        return None

    @staticmethod
    def _row_tried(tried: set, coord: tuple) -> bool:
        """坐标接近的行视为同一行(OCR 框可能有少量偏移)"""
        return any(abs(cx - coord[0]) <= 15 and abs(cy - coord[1]) <= 15 for cx, cy in tried)

    def _wait_chat_name(self, name: str) -> bool:
        """等待聊天面板顶部出现目标名字(装饰字体易丢字, 子串包含或相似度任一达标即可)"""
        timer = Timer(6).start()
        while not timer.reached():
            self.screenshot()
            text = self.O_FL_CHAT_NAME.detect_text(self.device.image)
            if text:
                text = text.strip()
                if text and (text in name or name in text or
                             difflib.SequenceMatcher(None, text, name).ratio() >= 0.7):
                    return True
            sleep(0.5)
        return False

    def _wait_chat_server(self, server: str) -> Optional[str]:
        """等待聊天面板右上角紫色区服名并与目标比对

        :return: 核对通过返回实际读到的区服文本; 超时(含读不到区服)返回 None
        """
        timer = Timer(5).start()
        last = ''
        while not timer.reached():
            self.screenshot()
            text = (self.O_FL_CHAT_SERVER.detect_text(self.device.image) or '').strip()
            if text and (text in server or server in text or
                         difflib.SequenceMatcher(None, text, server).ratio() >= 0.6):
                return text
            if text and text != last:
                logger.info(f'[点赞] 面板区服读作 {text}，与目标 {server} 不符')
                last = text
            sleep(0.5)
        if not last:
            logger.warning('[点赞] 未读到聊天面板紫色区服名(同区好友面板可能不显示)')
        return None

    def _click_thumb(self, name: str) -> bool:
        """点击点赞拇指并验证; 已点赞视为完成"""
        # 先短暂确认是否已点过(橙色拇指)
        timer = Timer(1.5).start()
        while not timer.reached():
            self.screenshot()
            if self.appear(self.I_FL_THUMB_LIKED, interval=0.5):
                logger.info(f'[点赞] {name} 今日已点赞过')
                return True
            sleep(0.3)
        before = self._read_thumb_count()
        for attempt in range(3):
            # 点白色拇指(匹配到哪点哪; 有「相伴N天」羁绊横幅时拇指会下移, 固定坐标会落空)
            if not self.appear_then_click(self.I_FL_THUMB_NORMAL, interval=0.5):
                logger.warning(f'[点赞] {name} 未匹配到白色拇指图标')
            timer = Timer(4).start()
            while not timer.reached():
                self.screenshot()
                if self.appear(self.I_FL_THUMB_LIKED, interval=0.5):
                    logger.info(f'[点赞] {name} 点赞成功')
                    return True
                after = self._read_thumb_count()
                if before is not None and after is not None and after == before + 1:
                    logger.info(f'[点赞] {name} 点赞成功')
                    return True
                sleep(0.5)
            logger.warning(f'[点赞] {name} 第 {attempt + 1} 次点击未见反馈，重试')
        return False

    def _read_thumb_count(self) -> Optional[int]:
        """读取聊天面板顶部点赞数字, 读不出返回 None

        ROI 扩大后可能扫到上方「相伴N天」羁绊横幅, 只取纯数字行(横幅行混汉字被排除), 取最下一行
        """
        try:
            results = self.O_FL_THUMB_COUNT.detect_and_ocr(self.device.image, logDisplay=False)
            rows = [r.ocr_text.strip().replace(' ', '') for r in results]
            rows = [t for t in rows if t.isdigit()]
            if not rows:
                return None
            return int(rows[-1])
        except (ValueError, TypeError):
            return None

    def _open_add_page(self) -> bool:
        """切到右侧添加页签(搜索非好友)"""
        logger.info('[点赞] 切换到添加页')
        timer = Timer(15).start()
        while not timer.reached():
            self.screenshot()
            if self.appear(self.I_FL_ADD_TAB, interval=0.5):
                return True
            self.click(self.C_FL_ADD_CLICK)
            sleep(1.5)
        logger.warning('[点赞] 切换添加页超时')
        return False

    def _ensure_search_server(self) -> bool:
        """搜索前将区服重置为全服(规定: 搜索点赞只走全服)"""
        if not self._open_area_popup():
            return False
        self.device.click(211, 257)  # 全服选项
        sleep(1.5)
        return True

    def _open_area_popup(self) -> bool:
        """打开选择区域弹窗"""
        timer = Timer(10).start()
        while not timer.reached():
            self.screenshot()
            if self.appear(self.I_FL_AREA_TITLE, interval=0.5):
                return True
            self.click(self.C_FL_AREA_OPEN)
            sleep(1.2)
        logger.warning('[点赞] 打开区域弹窗超时')
        return False

    def _like_by_search(self, target: str, name_check: bool) -> bool:
        """通过添加页搜索玩家并点赞(#ID 或名字均可, 可覆盖非好友)"""
        logger.info(f'[点赞] 搜索 {target}')
        # 清空搜索框并输入目标
        self.click(self.C_FL_SEARCH_CLEAR)
        sleep(0.5)
        self.click(self.C_FL_SEARCH_INPUT)
        sleep(1)
        if not self._input_text(target):
            logger.warning(f'[点赞] {target} 输入失败，跳过')
            return False
        sleep(0.8)
        self._wait_search_ready()
        self.click(self.I_FL_SEARCH_GO)
        sleep(2.5)
        # 搜索结果通常唯一, 直接点第一行
        row = self._find_search_result()
        if row is None:
            logger.warning(f'[点赞] 搜索 {target} 无结果')
            return False
        self.device.click(*row)
        sleep(2)
        # #ID 搜索跳过名字核对(OCR 读不到ID), 名字搜索按相似度核对
        if name_check and not target.startswith('#') and not self._wait_card_name(target.lstrip('#')):
            logger.warning(f'[点赞] {target} 卡片名字核对失败，跳过')
            self.click(self.C_FL_CARD_CLOSE)
            sleep(0.8)
            return False
        ok = self._click_card_thumb(target)
        self.click(self.C_FL_CARD_CLOSE)
        sleep(0.8)
        return ok

    def _input_text(self, text: str) -> bool:
        """输入文本到当前焦点框; 优先 u2.send_keys, 失败时 ASCII 回退 input text + MuMu 输入条确定"""
        try:
            self.device.u2.send_keys(text, clear=True)
            return True
        except Exception as e:
            logger.warning(f'[点赞] u2 输入失败: {e}')
        # 回退: adb input text + MuMu 顶部输入条确定按钮(仅 ASCII, 中文无法走此通道)
        is_ascii = all(ord(c) < 128 for c in text)
        if not is_ascii:
            logger.error(f'[点赞] 中文 {text} 无法通过 input text 输入(需 MuMu 输入法支持), 跳过')
            return False
        import subprocess
        serial = getattr(self.device, 'serial', None) or self.config.script.device.serial
        adb = getattr(self.device, 'adb_binary', None) or r'D:\platform-tools\adb.exe'
        subprocess.run([adb, '-s', serial, 'shell', 'input', 'text', text], check=False)
        sleep(1.5)
        # MuMu 顶部输入条的确定按钮(提交到自绘框)
        self.device.click(1094, 30)
        sleep(1.5)
        return True

    def _wait_search_ready(self, timeout: int = 15) -> bool:
        """等搜索按钮冷却结束(文本从 N秒 变回 搜索)"""
        timer = Timer(timeout).start()
        while not timer.reached():
            self.screenshot()
            text = self.O_FL_SEARCH_GO_STATE.detect_text(self.device.image) or ''
            if '搜索' in text and '秒' not in text:
                return True
            sleep(1)
        logger.warning('[点赞] 等待搜索冷却超时')
        return False

    def _find_search_result(self) -> Optional[tuple]:
        """等待搜索结果出现, 返回第一行点击坐标"""
        timer = Timer(8).start()
        while not timer.reached():
            self.screenshot()
            results = self.O_FL_SEARCH_NAME.detect_and_ocr(self.device.image)
            if results:
                r = results[0]
                x = self.O_FL_SEARCH_NAME.roi[0] + r.box[0, 0]
                y = self.O_FL_SEARCH_NAME.roi[1] + r.box[0, 1]
                w = r.box[1, 0] - r.box[0, 0]
                h = r.box[2, 1] - r.box[0, 1]
                return (int(x + w / 2), int(y + h / 2))
            sleep(0.8)
        return None

    def _wait_card_name(self, name: str) -> bool:
        """等待悬浮卡顶部出现目标名字(装饰字体易丢字, 子串或低相似度兜底)"""
        timer = Timer(5).start()
        while not timer.reached():
            self.screenshot()
            text = (self.O_FL_CARD_NAME.detect_text(self.device.image) or '').strip()
            if text and (name in text or text in name or
                         difflib.SequenceMatcher(None, text, name).ratio() >= 0.5):
                return True
            sleep(0.5)
        return False

    def _click_card_thumb(self, name: str) -> bool:
        """点击悬浮卡点赞拇指并以点赞数+1验证; 已点过(数字无变化)视为完成"""
        before = self._read_card_count()
        for attempt in range(3):
            self.click(self.C_FL_CARD_THUMB)
            timer = Timer(4).start()
            while not timer.reached():
                self.screenshot()
                after = self._read_card_count()
                if before is not None and after is not None and after == before + 1:
                    logger.info(f'[点赞] {name} 点赞成功')
                    return True
                sleep(0.5)
            logger.warning(f'[点赞] {name} 第 {attempt + 1} 次点击未见反馈')
        if before is not None:
            logger.info(f'[点赞] {name} 疑似今日已点赞，跳过')
            return True
        return False

    def _read_card_count(self) -> Optional[int]:
        """读取悬浮卡点赞数字"""
        try:
            text = self.O_FL_CARD_COUNT.detect_text(self.device.image)
            return int(re.sub(r'\D', '', text or ''))
        except (ValueError, TypeError):
            return None

    def _like_all_friends(self) -> int:
        """好友与跨区好友分组顺序点赞, 至 20 次上限"""
        liked = 0
        for cross in (False, True):
            if not self._expand_group(cross):
                continue
            liked += self._like_visible_friends(stop=20 - liked)
            if liked >= 20:
                break
        return liked

    # 列表 OCR 会混入状态标签/时间戳/分组计数, 不是好友名字
    LIKE_NAME_NOISE = re.compile(r'[/：:]|小时前|分钟前|天前|昨天|前天|^在线$|^离线$')

    def _like_visible_friends(self, stop: int) -> int:
        """遍历当前展开分组的列表逐个点赞; 名单按名字去重, 重名好友会漏点"""
        liked = 0
        done_names: set = set()
        last_texts: Optional[set] = None
        idle_pages = 0
        while liked < stop and idle_pages < 3:
            self.screenshot()
            results = self.O_FL_LIST_NAME.detect_and_ocr(self.device.image)
            texts = set()
            clicked = False
            for r in results:
                text = r.ocr_text.strip()
                if not text:
                    continue
                texts.add(text)
                if text in done_names or self.LIKE_NAME_NOISE.search(text):
                    continue
                done_names.add(text)
                x = self.O_FL_LIST_NAME.roi[0] + r.box[0, 0]
                y = self.O_FL_LIST_NAME.roi[1] + r.box[0, 1]
                w = r.box[1, 0] - r.box[0, 0]
                h = r.box[2, 1] - r.box[0, 1]
                self.device.click(int(x + w / 2), int(y + h / 2))
                sleep(0.8)
                if self._click_thumb(text):
                    liked += 1
                clicked = True
                if liked >= stop:
                    return liked
            if liked >= stop:
                break
            if not clicked:
                idle_pages += 1
            else:
                idle_pages = 0
            if last_texts is not None and texts and texts == last_texts:
                idle_pages += 1
            last_texts = texts
            if liked < stop:
                self.swipe(self.S_FL_LIST_UP, interval=1.2)
        return liked

    def run_store(self):
        if self.check_store_all_done():
            logger.info('[每日琐事] 商店任务全部完成，跳过')
            return
        self.goto_page(page_mall, confirm_wait=3)
        if self.config.daily_trifles.trifles_config.store_sign:
            self.run_store_sign()
        if self.config.daily_trifles.trifles_config.buy_sushi_count > 0:
            self.run_buy_sushi()
        self.goto_page(page_main)

    def run_store_sign(self):
        logger.hr('商店签到', 2)
        if self.config.daily_trifles.today_is_done('store_sign'):
            logger.info('[每日琐事] 今日已完成，跳过')
            return
        self.config.daily_trifles.done_record.store_sign_dt = datetime.now()
        self.goto_page(page_store_gift_room)
        self.screenshot()
        self.appear_then_click(self.I_GIFT_RECOMMEND, interval=1)
        logger.info('[每日琐事] 进入商店签到')
        sleep(1)  # 等个动画
        self.screenshot()
        if not self.appear(self.I_GIFT_SIGN):
            logger.warning('[每日琐事] 未找到礼包签到')
            return

        if self.ui_get_reward(self.I_GIFT_SIGN, click_interval=2.5):
            logger.info('[每日琐事] 领取礼包签到奖励')

    def run_buy_sushi(self):
        logger.hr('商店购买体力', 2)
        if self.config.daily_trifles.today_is_done('sushi'):
            logger.info('[每日琐事] 今日已完成，跳过')
            return
        # 进入Special
        while 1:
            from tasks.RichMan.assets import RichManAssets
            self.screenshot()
            if self.appear(RichManAssets.I_SIDE_CHECK_SPECIAL) and self.appear(self.I_SPECIAL_SUSHI):
                break
            if self.appear_then_click(RichManAssets.I_MALL_SUNDRY, interval=1):
                continue

        def detect_buy_count(base_element) -> (int, int):
            # 返回count,price
            MAX_PRICE = 9999
            MAX_COUNT = 9999
            roi = copy.deepcopy(base_element.roi_front)
            roi[0] = roi[0] + roi[2]
            roi[1] = roi[1] + roi[3] - 45
            roi[2] = 75
            roi[3] = 45
            self.O_STORE_SUSHI_PRICE.roi = roi
            _price = self.O_STORE_SUSHI_PRICE.detect_text(self.device.image)
            # 保守策略，避免OCR错误购买
            try:
                _price = int(_price)
            except Exception as e:
                _price = MAX_PRICE

            if _price < 60:
                return 0, MAX_PRICE
            _count = (_price - 60) / 20
            return _count, _price

        roi = None
        # 购买体力
        while 1:
            self.screenshot()
            # count, price = detect_buy_count(roi)
            # if count >= self.config.model.daily_trifles.trifles_config.buy_sushi_count:
            #     break
            logger.info(f"购买次数为: {self.config.daily_trifles.trifles_config.buy_sushi_count} 次")
            if self.appear(self.I_STORE_COST_TYPE_JADE):
                count, price = detect_buy_count(self.I_STORE_COST_TYPE_JADE)
                if count >= self.config.daily_trifles.trifles_config.buy_sushi_count:
                    break
                if self.ui_get_reward(self.I_STORE_COST_TYPE_JADE, click_interval=2.5):
                    logger.info(f"[每日琐事] 花费 {price} 勾玉购买体力")
                    continue

            if self.appear(self.I_SPECIAL_SUSHI):
                # 此处确定当前购买体力所需勾玉数量的位置,用于后续识别
                count, price = detect_buy_count(self.I_SPECIAL_SUSHI)
                if count >= self.config.daily_trifles.trifles_config.buy_sushi_count:
                    logger.info(f"已经购买 {count} 次, 退出购买")
                    break
                self.ui_click(self.I_SPECIAL_SUSHI, stop=self.I_STORE_COST_TYPE_JADE, interval=2)
                continue
        self.config.daily_trifles.done_record.sushi_dt = datetime.now()

    def run_courtyard_affairs(self):
        """庭院事务"""
        logger.hr('庭院事务', 2)
        self.goto_page(page_main)
        timeout_timer = Timer(3).start()
        while not timeout_timer.reached():
            self.screenshot()
            if self.appear(self.I_ENTER_COURTYARD_AFFAIRS, interval=1.2):
                self.goto_page(page_courtyard_affairs)
                timeout_timer.reset()
                break
        if timeout_timer.reached():
            logger.info('[每日琐事] 没有庭院事务，退出')
            return
        while True:
            self.screenshot()
            if self.appear(self.I_CHECK_IN_DAILY, interval=0.5):
                break
            if self.appear_then_click(self.I_ENTER_DAILY, interval=1):
                continue
        self.appear_then_click(self.I_ONE_COMPLETE, interval=1)
        self.goto_page(page_main)
        self.config.daily_trifles.done_record.courtyard_affairs_dt = datetime.now()

    def run_pickup_email(self):
        """领取邮件"""
        logger.hr('领取邮件', 2)
        self.goto_page(page_main)
        timeout_timer = Timer(3).start()
        while not timeout_timer.reached():
            self.screenshot()
            if self.appear_then_click(self.I_DT_HARVEST_MAIL_COPY2, interval=1.2) or \
                    self.appear_then_click(self.I_HARVEST_MAIL, interval=1.2) or \
                    self.appear_then_click(self.I_HARVEST_MAIL_COPY, interval=1.2):
                continue
            if self.appear_then_click(self.I_UI_CONFIRM, interval=1):
                continue
            if self.appear_then_click(self.I_HARVEST_MAIL_ALL, interval=2):
                timeout_timer.reset()
                continue
            if self.appear_then_click(self.I_READ_ALL_MAIL, interval=3):
                continue
        self.goto_page(page_main)
        self.config.daily_trifles.done_record.pickup_email_dt = datetime.now()

    def plan_next_dt(self):
        # 定时领体力（每天 12-14、20-22 时内各有 20 体力）
        now = datetime.now()
        # 如果时间在00:00-12:00之间则设定时间为当日 12 时
        if now.time() < time(12, 0):
            self.custom_next_run(task='DailyTrifles', custom_time=Time(12, 0), time_delta=0)
        # 如果时间在12:00-20:00之间则设定时间为当日 20 时
        elif time(12, 0) <= now.time() < time(20, 0):
            self.custom_next_run(task='DailyTrifles', custom_time=Time(20, 0), time_delta=0)
        # 如果时间在20:00-23:59之间则设定时间为次日 12 时
        else:
            self.custom_next_run(task='DailyTrifles', custom_time=Time(12, 0), time_delta=1)

    def check_store_all_done(self) -> bool:
        """判断商店任务是否都做完了, 做完了则不再进入商店"""
        if self.config.daily_trifles.trifles_config.store_sign and not self.config.daily_trifles.today_is_done('store_sign'):
            return False
        if self.config.daily_trifles.trifles_config.buy_sushi_count > 0 and not self.config.daily_trifles.today_is_done('sushi'):
            return False
        return True


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas2')
    d = Device(c)
    t = ScriptTask(c, d)

    t.run_guild_donate()

