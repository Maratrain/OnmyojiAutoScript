import re
import time
from datetime import datetime, timedelta

from module.base.timer import Timer
from module.exception import TaskEnd
from module.logger import logger
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main
from tasks.GuildActivityMonitor.assets import GuildActivityMonitorAssets


class ScriptTask(GameUi, GuildActivityMonitorAssets):

    # 通知新鲜度窗口: 超过此秒数的推送视为陈旧, 不触发, 避免历史推送在首次运行时被误触发
    NOTIFY_FRESHNESS_SECONDS = 30 * 60

    def run(self):
        """阴阳寮活动监控主函数"""
        if not self.check_run_days():
            raise TaskEnd('GuildActivityMonitor')
        self.goto_page(page_main)
        keyword_map = self.build_keyword_map()
        self.monitor_activities(keyword_map)

    def check_run_days(self) -> bool:
        """检查今天是否在运行日期内，设置下次运行时间"""
        monitor_config = self.config.guild_activity_monitor.guild_activity_monitor_combat_time
        now = datetime.now()
        today = now.weekday() + 1
        run_days = sorted({day for day in map(int, re.findall(r'\d+', monitor_config.run_days)) if 1 <= day <= 7})
        if not run_days:
            logger.warning(f"运行日期配置无效: {monitor_config.run_days}，跳过 GuildActivityMonitor")
            return False

        in_run_days = today in run_days
        candidate_days = [day for day in run_days if day != today] if in_run_days else run_days
        delta_days = min((day - today) % 7 for day in candidate_days)
        next_date = now + timedelta(days=delta_days or 7)

        server_update = self.config.guild_activity_monitor.scheduler.server_update
        use_server_time = (server_update.hour, server_update.minute, server_update.second) != (9, 0, 0)
        next_target = datetime.combine(next_date.date(), server_update) if use_server_time else next_date
        status = '在' if in_run_days else '不在'
        action = '本次继续执行' if in_run_days else '跳过 GuildActivityMonitor'
        logger.info(f"今天是周{today}，{status}配置运行日期({monitor_config.run_days})内，"
                    f"{action}，下次运行时间: {next_target}")
        self.set_next_run(task='GuildActivityMonitor', success=None, finish=False, server=False, target=next_target)
        return in_run_days

    def build_keyword_map(self) -> dict:
        """构建活动关键字到任务名的映射"""
        guild_config = self.config.guild_activity_monitor.guild_activity
        keyword_map = {
            '道馆': 'Dokan' if guild_config.Dokan else None,
            '狭间': 'AbyssShadows' if guild_config.AbyssShadows else None,
            '宴会': 'GuildBanquet' if guild_config.GuildBanquet else None,
            '退治': 'DemonRetreat' if guild_config.DemonRetreat else None,
        }
        keyword_map = {k: v for k, v in keyword_map.items() if v}
        logger.info(f"监控活动: {list(keyword_map.keys())}")
        return keyword_map

    def monitor_activities(self, keyword_map: dict):
        """启动活动监控循环"""
        monitor_config = self.config.guild_activity_monitor.guild_activity_monitor_combat_time
        interval = monitor_config.detection_interval
        use_ocr = monitor_config.use_ocr
        keywords = list(keyword_map.keys())
        logger.info(f"开始阴阳寮活动监控，持续{monitor_config.monitor_duration}分钟，"
                    f"每{interval}秒检测一次，模式: {'ocr' if use_ocr else 'adb'}")

        check_timer = Timer(monitor_config.monitor_duration * 60)
        check_timer.start()
        log_timer = Timer(60)
        log_timer.start()

        if use_ocr:
            init_keyword = self.get_notification_info_ocr(keywords)
            logger.info(f"初始通知关键字: {init_keyword or '无'}")
        # ADB 模式无需启动快照: 系统通知列表是持久累积, 启动前已到达的推送
        # 会因 when 未超过 last_triggered_when 被跳过, 同一推送只触发一次

        stuck_interval = Timer(280)
        while True:
            if not stuck_interval.started() or stuck_interval.reached():
                self.device.stuck_record_clear()
                self.device.stuck_record_add('PAUSE')
                stuck_interval.reset()

            if check_timer.reached():
                logger.info("监控时间到，任务结束")
                raise TaskEnd('GuildActivityMonitor')

            if log_timer.reached():
                remaining = int(check_timer.remain() // 60)
                logger.info(f"监控中... 剩余时间: {remaining}分钟")
                log_timer.reset()

            self.screenshot()

            if use_ocr:
                notification_text = self.get_notification_info_ocr(keywords)
                if notification_text and notification_text != init_keyword:
                    self.trigger_activity_task(notification_text, keyword_map[notification_text])
            else:
                self.check_adb_notifications(keywords, keyword_map, monitor_config)

            time.sleep(interval)

    def trigger_activity_task(self, keyword, task_name):
        """检测到活动关键字后拉起对应任务并结束监控"""
        logger.info(f"检测到关键字 '{keyword}'，启动任务: {task_name}")
        monitor_config = self.config.guild_activity_monitor.guild_activity_monitor_combat_time
        self.set_next_run(task=task_name, success=False, finish=False, server=False, target=datetime.now())
        self.set_next_run(task='GuildActivityMonitor', success=False, finish=False, server=False,
                          target=datetime.now() + timedelta(minutes=monitor_config.recheck_interval))
        raise TaskEnd('GuildActivityMonitor')

    def check_adb_notifications(self, keywords: list, keyword_map: dict, monitor_config):
        """ADB模式: 遍历当前通知, 命中关键字且新鲜且未触发过则拉起对应任务

        通过 last_triggered_when 跨周期去重, 同一推送只触发一次, 修复宴会推送在
        监控启动前已到达时被全局最新 when 门控吞掉的问题; 通过新鲜度窗口跳过
        陈旧通知, 避免历史推送在首次运行时被误触发。
        """
        now_ms = time.time() * 1000
        last_triggered = monitor_config.last_triggered_when
        for keyword, when in self.get_keyword_notifications(keywords):
            if (now_ms - when) / 1000 > self.NOTIFY_FRESHNESS_SECONDS:
                continue
            if when > float(last_triggered.get(keyword, 0)):
                logger.info(f"[寮活动-ADB] 命中关键字 '{keyword}'"
                            f"（通知时间 {datetime.fromtimestamp(when / 1000).strftime('%H:%M:%S')}），"
                            f"新鲜度内且未触发过")
                # 先持久化去重标记再触发任务(trigger 内会 raise TaskEnd),
                # 否则下次重进监控会因标记未落盘而重复触发
                self.config.lock_config.acquire()
                try:
                    last_triggered[keyword] = when
                    self.config.save()
                finally:
                    self.config.lock_config.release()
                self.trigger_activity_task(keyword, keyword_map[keyword])

    def get_keyword_notifications(self, keywords: list) -> list:
        """通过adb读取系统通知，返回所有命中关键字的 (关键字, when) 列表"""
        try:
            output = self.device.adb_shell(['dumpsys', 'notification', '--noredact'])
            results = []
            for block, time_str in re.findall(r'(when=(\d+)[\s\S]*?(?=when=|\Z))', output):
                when = float(time_str)
                for keyword in keywords:
                    if keyword in block:
                        results.append((keyword, when))
                        break
            return results
        except Exception as e:
            logger.warning(f"获取通知失败: {e}")
            return []

    def get_notification_info_ocr(self, keywords: list) -> str:
        """通过OCR识别屏幕通知区域，返回活动关键字"""
        for keyword in keywords:
            result = self.O_GUILD_ACTIVITY_NOTIFY.ocr(self.device.image, keyword=keyword)
            if result != (0, 0, 0, 0):
                return keyword
        return ''


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)
    t.run()
