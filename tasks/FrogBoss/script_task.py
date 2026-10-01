# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from cached_property import cached_property
from datetime import datetime
import time
import requests
import re
import json
from pathlib import Path

from module.exception import GameStuckError, TaskEnd
from module.logger import logger
from module.atom.click import RuleClick
from module.atom.image import RuleImage
from module.base.timer import Timer
from module.notify.notify import Notifier

from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main
from tasks.Component.RightActivity.right_activity import RightActivity
from tasks.Component.GeneralBattle.assets import GeneralBattleAssets
from tasks.Component.config_base import TimeDelta
from tasks.FrogBoss.assets import FrogBossAssets
from tasks.FrogBoss.config import Strategy
from tasks.FrogBoss.record_reader import read_record_rows
from tasks.FrogBoss.frog_oas import (OasHistory, fetch_predictions, fingerprint,
                                     choose_follow, format_decision, format_result,
                                     side_name, same_lineup, slot_label, FOLLOW_POLL_INTERVAL)
from tasks.FrogBoss.oas_sources import resolve_follow_list, blogger_name

STRATEGY_LABELS = {
    Strategy.Majority: '押人数多的一方',
    Strategy.Minority: '押人数少的一方',
    Strategy.Bilibili: '跟随B站博主',
    Strategy.Dashen: '综合大神推荐',
    Strategy.Oas: '加权投票',
    Strategy.FollowBlogger: '跟单指定博主',
    Strategy.AlwaysRed: '永远押红方',
    Strategy.AlwaysBlue: '永远押蓝方',
}


class ScriptTask(RightActivity, FrogBossAssets, GeneralBattleAssets):
    @cached_property
    def oas_history(self):
        instance = re.sub(r'[^\w.-]', '_', self.config.config_name)
        return OasHistory(Path('data/frog_oas') / f'{instance}.jsonl')

    @cached_property
    def frog_notifier(self) -> Notifier:
        frog = self.config.model.frog_boss.frog_boss_config
        notifier = Notifier(frog.notify_config, enable=frog.notify_enable)
        notifier.config_name = self.config.config_name
        return notifier

    def frog_notify(self, title: str, content: str = ''):
        """对弈竞猜环节推送：开关关闭或推送失败都不影响任务本身"""
        if not self.config.model.frog_boss.frog_boss_config.notify_enable:
            return
        try:
            self.frog_notifier.push(title=title, content=content)
        except Exception as e:
            logger.exception(f'[对弈竞猜] 推送通知失败: {title}')

    def winner_name(self, result) -> str:
        if result is None:
            return '未知'
        return '左方' if result else '右方'

    def record_oas_history_page(self):
        if self.config.model.frog_boss.frog_boss_config.strategy_frog not in (Strategy.Oas, Strategy.FollowBlogger):
            return
        timer = Timer(10).start()
        while not timer.reached():
            self.screenshot()
            if self.appear(self.I_FROG_LOG_CHECK):
                break
            self.appear_then_click(self.I_FROG_LOG, interval=2)
        else:
            logger.warning('[对弈竞猜-加权投票] 记录页面打开超时，跳过历史补结算')
            return
        try:
            # 只读取当前可见的记录行，绝不滚动记录页
            readings = []
            for _ in range(2):
                self.screenshot()
                if not self.appear(self.I_FROG_LOG_CHECK):
                    break
                readings.append(read_record_rows(self.device.image, self))
            if len(readings) != 2 or readings[0] != readings[1]:
                self.oas_history.append('unverified_result', reason='unstable_record_page')
                logger.warning('[对弈竞猜-加权投票] 记录页面两次读取结果不稳定，跳过补结算')
                self.frog_notify('历史补结算跳过', '记录页面两次读取结果不稳定，本轮未补结算')
            else:
                settle_lines = []
                for stamp, won, side in dict.fromkeys(readings[0]):
                    result = self.oas_history.settle_record(stamp, won, selected_side=side)
                    if result is not None:
                        result_text = format_result(result)
                    else:
                        result_text = '无对应跟单决策，结果暂记为未验证'
                    label = slot_label(stamp)
                    logger.info(f'[对弈竞猜-加权投票] 记录页补结算: {label} {result_text}，时间={stamp}，'
                                f"{'胜' if won else '负'}，本方押 {side_name(side)}")
                    settle_lines.append(f"{label} {'胜' if won else '负'}（本方押 {side_name(side)}）: {result_text}")
                if settle_lines:
                    self.frog_notify('历史补结算', '\n'.join(settle_lines))
        finally:
            timer = Timer(10).start()
            while not timer.reached():
                self.screenshot()
                if not self.appear(self.I_FROG_LOG_CHECK) and self.appear(self.I_FROG_CHECK):
                    break
                self.appear_then_click(self.I_FROG_LOG_CLOSE, interval=2)
            else:
                # 关不上说明界面状态已异常，继续跑主循环会空转，必须抛错
                raise GameStuckError('对弈竞猜记录页面关闭超时')

    def enter_frog_boss(self):
        self.screenshot()
        if self.appear(self.I_FROG_CHECK) or self.appear(self.I_FROG_LOG_CHECK):
            return
        self.enter(self.I_FROG_BOSS_ENTER)
        if not self.wait_until_appear(self.I_FROG_CHECK, wait_time=10):
            raise GameStuckError('进入活动后未检测到对弈竞猜页面')

    def _try_next_competition_fallback(self, idle_timer):
        if not self.appear(self.I_FROG_CHECK):
            idle_timer.reset()
            return False
        if idle_timer.reached() and self.appear_then_click(self.I_NEXT_COMPETITION, interval=1):
            logger.info('[对弈竞猜] 界面无操作 5 秒，保底点击下一局')
            idle_timer.reset()
            return True
        return False

    def run(self):
        self.enter_frog_boss()
        strategy = self.config.model.frog_boss.frog_boss_config.strategy_frog
        self.frog_notify('对弈竞猜开始', f"本次策略: {STRATEGY_LABELS.get(strategy, strategy)}")
        history_checked = False
        idle_timer = Timer(5).start()
        # 进入主界面
        while 1:
            self.screenshot()
            if self._try_next_competition_fallback(idle_timer):
                continue

            if not history_checked and self.config.model.frog_boss.frog_boss_config.strategy_frog in (Strategy.Oas, Strategy.FollowBlogger):
                if (self.appear(self.I_FROG_LOG_CHECK) or self.appear(self.I_BETTED)
                        or self.appear(self.I_FROG_BOSS_REST)
                        or (self.appear(self.I_BET_LEFT) and self.appear(self.I_BET_RIGHT))):
                    self.record_oas_history_page()
                    history_checked = True
                    idle_timer.reset()
                    continue

            # 已经下注
            if self.appear(self.I_BETTED):
                logger.info('已下注')
                self.frog_notify('本场已下注', '检测到本场已完成押注，等待开奖')
                break
            # 休息中
            if self.appear(self.I_FROG_BOSS_REST):
                logger.info('[对弈竞猜] 对弈休息中')
                self.frog_notify('对弈休息中', '当前处于休息时段，本轮无竞猜')
                break
            # 竞猜成功
            if self.appear(self.I_BET_SUCCESS):
                logger.info('竞猜成功')
                result = self.detect()
                self.frog_notify('竞猜成功', f"本场开奖: {self.winner_name(result)}获胜，竞猜成功")
                while 1:
                    self.screenshot()
                    if self._try_next_competition_fallback(idle_timer):
                        continue
                    if self.appear(self.I_BET_LEFT) and self.appear(self.I_BET_RIGHT):
                        break
                    if self.appear_then_click(self.I_BET_SUCCESS_BOX, interval=1):
                        idle_timer.reset()
                        continue
                    if self.appear_then_click(self.I_REWARD, interval=2):
                        idle_timer.reset()
                        continue
                    if self.appear_then_click(self.I_NEXT_COMPETITION, interval=4):
                        idle_timer.reset()
                        continue
                continue
            # 竞猜失败
            if self.appear(self.I_BET_FAILURE):
                logger.info('竞猜失败')
                result = self.detect()
                self.frog_notify('竞猜失败', f"本场开奖: {self.winner_name(result)}获胜，竞猜失败")
                if self.ui_click_until_disappear(self.I_NEXT_COMPETITION):
                    idle_timer.reset()
                continue
            # 正式竞猜
            if self.appear(self.I_BET_LEFT) and self.appear(self.I_BET_RIGHT):
                self.do_bet()
                idle_timer.reset()
                continue

        logger.info('[对弈竞猜] 对弈竞猜结束')
        self.next_run()
        next_run = self.config.model.frog_boss.scheduler.next_run
        self.frog_notify('任务结束', f"对弈竞猜结束，下次运行: {next_run}")
        raise TaskEnd('FrogBoss')

    def next_run(self):
        time = self.config.model.frog_boss.frog_boss_config.before_end_frog
        time_delta = TimeDelta(hours=time.hour, minutes=time.minute, seconds=time.second)
        time_now = datetime.now()
        time_set = time_now.replace(minute=0, second=0, microsecond=0)
        if 10 <= time_now.hour < 12:
            time_set = time_set.replace(hour=14)
        elif 12 <= time_now.hour < 14:
            time_set = time_set.replace(hour=16)
        elif 14 <= time_now.hour < 16:
            time_set = time_set.replace(hour=18)
        elif 16 <= time_now.hour < 18:
            time_set = time_set.replace(hour=20)
        elif 18 <= time_now.hour < 20:
            time_set = time_set.replace(hour=22)
        elif 20 <= time_now.hour < 22:
            time_set = time_set.replace(hour=0) + TimeDelta(days=1)
        elif 22 <= time_now.hour < 24:
            time_set = time_set.replace(hour=12) + TimeDelta(days=1)
        else:
            time_set = time_set.replace(hour=12)

        self.set_next_run(task='FrogBoss', target=time_set - time_delta)

    def do_bet(self):
        logger.hr('下注', level=2)
        self.screenshot()
        count_left = self.O_LEFT_COUNT.ocr(self.device.image)
        count_right = self.O_RIGHT_COUNT.ocr(self.device.image)
        blogger_text = ''
        match self.config.model.frog_boss.frog_boss_config.strategy_frog:
            case Strategy.Majority:
                click_image = self.I_BET_LEFT if count_left > count_right else self.I_BET_RIGHT
            case Strategy.Minority:
                click_image = self.I_BET_LEFT if count_left < count_right else self.I_BET_RIGHT
            case Strategy.Bilibili:
                click_image = self.I_BET_LEFT if count_left > count_right else self.I_BET_RIGHT
            case Strategy.Dashen:
                click_image = self.get_dashen(count_left, count_right)
            case Strategy.Oas:
                signature = fingerprint(self.device.image)
                # 拉取预测为纯网络操作（28 位大神逐个请求），期间无点击，需维持设备心跳
                predictions = fetch_predictions(self.oas_history, progress=self.device.stuck_record_clear)
                try:
                    decision = self.oas_history.choose(signature, count_left, count_right, predictions)
                except ValueError as exc:
                    raise GameStuckError(str(exc)) from exc
                logger.info(f'[对弈竞猜-加权投票] 决策: {format_decision(decision)}')
                # 拉取预测可能跨越轮次切换，绝不点击过期画面
                self.screenshot()
                if not same_lineup(signature, fingerprint(self.device.image)):
                    raise GameStuckError('等待预测期间对局阵容发生变化')
                if not (self.appear(self.I_BET_LEFT) and self.appear(self.I_BET_RIGHT)):
                    raise GameStuckError('等待预测期间竞猜已关闭')
                click_image = self.I_BET_LEFT if decision['side'] == 'LEFT' else self.I_BET_RIGHT
            case Strategy.FollowBlogger:
                # 博主解析与预测抓取均为纯网络操作，期间无点击，先重置卡死检测
                self.device.stuck_record_clear()
                uids = resolve_follow_list(self.config.model.frog_boss.frog_boss_config.follow_bloggers)
                if not uids:
                    raise GameStuckError('跟单博主列表为空或无法识别，请检查 follow_bloggers 配置')
                signature = fingerprint(self.device.image)
                decision = choose_follow(self.oas_history, signature, count_left, count_right, uids,
                                         wait=self.wait_for_follow_poll)
                logger.info(f'[对弈竞猜-跟单] 决策: {format_decision(decision)}')
                if decision.get('mode') == 'follow_blogger':
                    blogger_text = blogger_name(decision.get('source_uid'))
                else:
                    blogger_text = '全部博主无预测，已回退人数多'
                # 等待发帖可能跨越轮次切换，绝不点击过期画面
                self.screenshot()
                if not same_lineup(signature, fingerprint(self.device.image)):
                    raise GameStuckError('等待预测期间对局阵容发生变化')
                if not (self.appear(self.I_BET_LEFT) and self.appear(self.I_BET_RIGHT)):
                    raise GameStuckError('等待预测期间竞猜已关闭')
                click_image = self.I_BET_LEFT if decision['side'] == 'LEFT' else self.I_BET_RIGHT
            case Strategy.AlwaysRed:
                click_image = self.I_BET_LEFT
            case Strategy.AlwaysBlue:
                click_image = self.I_BET_RIGHT
            case _:
                raise ValueError(f'Unknown bet mode: {self.config.model.frog_boss.frog_boss_config.strategy_frog}')
        logger.info(f'策略为 {self.config.model.frog_boss.frog_boss_config.strategy_frog}，下注 {click_image}')
        side_text = '红方（左）' if click_image is self.I_BET_LEFT else '蓝方（右）'
        strategy_now = self.config.model.frog_boss.frog_boss_config.strategy_frog
        notify_content = (f"策略: {STRATEGY_LABELS.get(strategy_now, strategy_now)}\n"
                          f"红方 {count_left} 票 / 蓝方 {count_right} 票\n押 {side_text}")
        if blogger_text:
            notify_content += f"\n跟单博主: {blogger_text}"
        self.frog_notify('下注决策', notify_content)
        self.ui_click_until_disappear(click_image)
        if not self.confirm_bet():
            return
        self.frog_notify('下注完成', f"本场押注 {side_text} 完成，等待开奖")

    def select_gold_30(self) -> bool:
        """选中 30 万档：只点袋身上部，避开下部的获胜奖励说明角标（误触会弹出说明弹窗）"""
        if not self.appear(self.I_GOLD_30):
            return False
        x, y, width, height = self.I_GOLD_30.roi_front
        area = (x + width // 4, y + height // 8, width // 2, height // 3)
        self.click(RuleClick(roi_front=area, roi_back=area, name='FB_GOLD_30_SELECT'))
        return True

    def confirm_bet(self) -> bool:
        """选档并提交下注，返回是否完成下注（False 为对局已进入休息）

        获胜奖励说明弹窗为模态，弹窗后方的金额袋、鼓面确认键仍能模板匹配，
        不先关闭会点穿弹窗；检测到弹窗必须优先点左侧空白关闭并重新截图。
        注意：I_REWARD_CLOSE（右上角红×）实为下注界面的退出按钮，绝非弹窗关闭键，严禁加入本循环。
        """
        logger.info('[对弈竞猜] 正式下注')
        timer = Timer(9).start()
        gold_selected = False
        submit_attempts = 0
        while not timer.reached():
            self.screenshot()
            if self.appear(self.I_BETTED):
                return True
            if self.appear(self.I_FROG_BOSS_REST):
                logger.info('[对弈竞猜] 对局已进入休息，本场无需下注')
                return False
            if self.appear(self.I_GOLD_30_CHECK):
                logger.info('[对弈竞猜] 检测到获胜奖励说明弹窗，点击左侧空白关闭')
                self.click(self.C_RANDOM_LEFT, interval=2)
                continue
            if self.appear_then_click(self.I_UI_CONFIRM, interval=2):
                continue
            if self.appear_then_click(self.I_UI_CONFIRM_SAMLL, interval=2):
                continue
            if not gold_selected:
                if self.select_gold_30():
                    gold_selected = True
                continue
            if submit_attempts < 3 and self.appear_then_click(self.I_BET_SURE, interval=3):
                submit_attempts += 1
                continue
        raise GameStuckError(
            f'下注确认超时: gold_selected={gold_selected}, submit_attempts={submit_attempts}，本场押注可能已截止'
        )

    def wait_for_follow_poll(self, seconds_left):
        """跟单轮询等待：等一段时间再让 choose_follow 重拉预测。

        等待期间持续截图维持设备心跳；返回 False 表示到场已晚，不再等待。
        """
        interval = max(1.0, min(float(FOLLOW_POLL_INTERVAL), seconds_left))
        logger.info(f'[对弈竞猜-跟单] 博主尚未发布本场预测，{interval:.0f} 秒后重试（本场剩余可等 {seconds_left:.0f} 秒）')
        timer = Timer(interval)
        timer.start()
        while not timer.reached():
            time.sleep(1)
            # 等待期间无任何点击操作，必须持续重置卡死检测，否则 60 秒即被误判为游戏卡死
            self.device.stuck_record_clear()
            self.screenshot()
        return seconds_left - interval > 0

    def detect(self) -> bool:
        """
        检测是左边赢了还是右边赢的
        :return: True 左边赢了，False 右边赢了，无法识别时返回 None
        """
        if self.appear(self.I_SUCCESS_LEFT) and self.appear(self.I_FAILURE_RIGHT):
            result = True
            logger.info('左边赢了')
        elif self.appear(self.I_SUCCESS_RIGHT) and self.appear(self.I_FAILURE_LEFT):
            result = False
            logger.info('右边赢了')
        else:
            result = None
        return result

    def get_bilibili(self) -> RuleImage:
        """
        获取博主的策略选择
        :return:
        """
        pass

    def get_dashen(self, count_left, count_right) -> RuleImage:
        """
        获取博主的策略选择，整合多个博主的投注策略，并返回最终的下注建议
        :return: 'left' 或 'right' 的下注目标
        """
        logger.info('正在获取多位大神UP主的策略')
        # 定义正则表达式
        red_regex = re.compile(r'(押红|押左|压红|压左|红方|红色|我红|我左|红优|左|红六|红七|红八|红九|红十|91开|82开|73开|64开)')
        blue_regex = re.compile(r'(押蓝|押右|压蓝|压右|蓝方|蓝色|我蓝|我右|蓝优|右|蓝六|蓝七|蓝八|蓝九|蓝十|19开|28开|37开|46开)')

        # 获取 feedId 的函数
        def get_feed_id(uid):
            url = f'https://inf.ds.163.com/v1/web/feed/basic/getSomeOneFeeds?feedTypes=1,2,3,4,6,7,10,11&someOneUid={uid}'
            response = requests.get(url)
            if response.status_code == 200:
                data = response.json()
                if 'result' in data and 'feeds' in data['result'] and len(data['result']['feeds']) > 0:
                    return data['result']['feeds'][0]['id']
            return None
        
        # 获取 feed 详细信息的函数
        def get_feed_details(feed_id):
            url = f'https://inf.ds.163.com/v1/web/feed/basic/facade?feedId={feed_id}'
            response = requests.get(url)
            if response.status_code == 200:
                data = response.json()
                try:
                    user_nick = data['result']['userInfos'][0]['user']['nick']
                    create_time = data['result']['feed']['createTime']
                    content_json = data['result']['feed']['content']
                    content_data = json.loads(content_json)
                    body_text = content_data['body']['text']
                    return {
                        'user_nick': user_nick,
                        'create_time': create_time,
                        'body_text': body_text
                    }
                except (KeyError, IndexError, json.JSONDecodeError):
                    return None
            return None
        
        # 检查发布时间是否符合规则
        def is_time_valid(create_time):
            # 定义时间段
            valid_time_ranges = [(10, 12), (12, 14), (14, 16), (16, 18), (18, 20), (20, 22), (22, 24)]
            now = datetime.now()
            # now = datetime(year=2024, month=10, day=3, hour=19, minute=45, second=0)  # 指定时间读取历史文章
            
            # 获取发布时间
            post_time = datetime.fromtimestamp(create_time / 1000)  # 假设 create_time 是毫秒级时间戳
            post_hour = post_time.hour
            
            # 检查发布时间是否在有效时间段内
            for start, end in valid_time_ranges:
                if start <= post_hour < end and start <= now.hour < end:
                    return True
            return False

        # 分析 body_text 来判断投注结果
        def analyze_bet(body_text):
            red_span=9999
            blue_span=9999
            if red_regex.search(body_text):
                red_span=red_regex.search(body_text).start()
            if blue_regex.search(body_text):
                blue_span=blue_regex.search(body_text).start()
            if red_span < blue_span:
                return 'LEFT'
            elif red_span > blue_span:
                return 'RIGHT'
            return 'Unknown'

        # 提供的 uid 列表
        uids = [
            {"name": "面灵气喵", "id": "462382f1127b46c5add1185d88f0ea40"},
            {"name": "余岁岁", "id": "54399446d5084a0e8878dac8f6ff56d0"},
            {"name": "七面相", "id": "840742d60e4a43208605ae68ca8c3f64"},
            {"name": "待机中的徐ok", "id": "c3c989fae4074d04b478b8ba47ae4120"},
            {"name": "雯雯", "id": "aaa923436aa440df9ac1ee3f47387b99"},
            {"name": "晨时微凉", "id": "72584a679e2f45b6859566b5523400d5"},
            {"name": "梅布斯尼", "id": "3d4726d99f2642a485729695b798cb8c"},
            {"name": "鸽海成路", "id": "1d2dcbbd7e3d481c8d0f27ba4ff0dc71"},
            {"name": "徐清林", "id": "21657a558bdd4ddfb6501298350336e7"},
            {"name": "不包邮哦亲", "id": "0e4e0c5a1e494a1fa9a58ac55de689c1"},
            {"name": "天真珈百璃", "id": "30e383c884f844a18a7a76fe3c1e888f"},
            {"name": "薛定谔家查查尔", "id": "d9dc2a75497c4a91b2db1e909a36544d"},
            {"name": "嘤嘤井", "id": "e7107cd3010e418da26672669d8eeb5e"},
            {"name": "Prince班崎", "id": "74adeb1bfb2b4cf382edbbb430da2149"},
            {"name": "靠脸混饭", "id": "e87f855f36f24b34b9d8f8a4fb2d62b2"},
            {"name": "夜神月丶L", "id": "82de68c7672e4b6da65493fb829b57b6"},
            {"name": "是大荣啦", "id": "f6d6bb15d6024200a985752e2ab4c373"},
            {"name": "炒饭菌", "id": "06e2bba14a914012bc8064601cfa19ea"},
            {"name": "清流不加班", "id": "8982241de1844638b4bb455139b8dcc0"},
            {"name": "槐夏三十", "id": "a9724e98c1cb4a4e931ebc3f467ea73d"},
            {"name": "落沫颜", "id": "e9b0a16325af46628e8dfb9e7942cf1d"},
            {"name": "Mico林木森", "id": "b6b5bc8277e34f69aeca018db0081397"},
            {"name": "查查尔", "id": "d9dc2a75497c4a91b2db1e909a36544d"},
            {"name": "CC南浔", "id": "74db771d92a54c28ae3e98d19aa565a3"},
            {"name": "冰七喜Den", "id": "e498e524252041e29999b38e57c4df1d"},
            {"name": "行水姑娘", "id": "30b0c2923faa483f95572c324a5bc910"},
            {"name": "更慕林", "id": "e32aedbdd8da46a5b5b497a16c4b7658"}
            # ... 可以添加更多 uid
        ]


        # 主函数，遍历这批 uid
        count_uper_left = 0  # 统计博主投注左侧红方次数
        count_uper_right = 0  # 统计博主投注右侧蓝方次数

        for user in uids:
            uid = user['id']
            name = user['name']
            feed_id = get_feed_id(uid)
            if feed_id:
                details = get_feed_details(feed_id)
                # 检查 create_time 和 body_text
                if details and is_time_valid(int(details['create_time'])) and details['body_text']:
                    bet_result = analyze_bet(details['body_text'])
                    bet_rate = (re.compile(r"([5-9]\d%|\d+开|[一二三四五六七八九十零]+开|([红蓝][一二三四五六七八九十零,0-9])+)")
                            .search(details.get('body_text')))
                    if bet_rate:
                        bet_rate = ',' + bet_rate.group()
                    else:
                        bet_rate = ''
                    # 输出博主结论，可省略
                    # logger.info(f"{name}({details['user_nick']}) has bet on the {bet_result}{bet_rate}")

                    # 根据投注结果更新统计
                    if bet_result == 'LEFT':
                        count_uper_left += 1
                    elif bet_result == 'RIGHT':
                        count_uper_right += 1

        # 最终输出决策
        if count_uper_left > count_uper_right:
            logger.info(f"最终决策: 最佳下注为左边({count_uper_left}:{count_uper_right})")
            return self.I_BET_LEFT  # 返回下注的目标是左边
        elif count_uper_right > count_uper_left:
            logger.info(f"最终决策: 最佳下注为右边({count_uper_right}:{count_uper_left})")
            return self.I_BET_RIGHT  # 返回下注的目标是右边
        else:
            logger.info("最终决策: 左右票数相等，默认押少数方")
            # 若五五开则投注少数博反压奖励
            if count_left < count_right:
                return self.I_BET_LEFT
            else:
                return self.I_BET_RIGHT


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device
    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)

    t.run()

