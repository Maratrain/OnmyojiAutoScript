# This Python file uses the following encoding: utf-8
# 小号轮换：同一账号下不同区服的角色逐个登录，执行每日琐事/每周琐事/协作扫描后切换下一个
import random
from datetime import datetime, time as dt_time, timedelta

from module.exception import TaskEnd, RequestHumanTakeover
from module.logger import logger

from module.base.timer import Timer
from module.notify.notify import Notifier
from tasks.AreaBoss.script_task import ScriptTask as AreaBossScriptTask
from tasks.Component.SwitchAccount.switch_account import SwitchAccount
from tasks.Component.SwitchAccount.switch_account_config import AccountInfo
from tasks.DailyTrifles.config import DoneRecord
from tasks.DailyTrifles.script_task import ScriptTask as DailyTriflesScriptTask
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main, page_mall
from tasks.RichMan.mall.consignment import Consignment as ConsignmentMixin
from tasks.WantedQuests.script_task import ScriptTask as WantedQuestsScriptTask
from tasks.WeeklyTrifles.script_task import ScriptTask as WeeklyTriflesScriptTask


class _ConfigSectionProxy:
    """
    Config 浅代理：仅把指定配置节替换为传入对象，其余属性透传真实配置。
    用于给每个小号注入独立的琐事配置节（含独立的完成记录），不改动配置文件，
    各小号共用用户在「每日琐事」「每周琐事」配置页里设置的项目开关。
    """

    def __init__(self, real, overrides: dict):
        object.__setattr__(self, '_real', real)
        object.__setattr__(self, '_overrides', overrides)

    def __getattr__(self, name):
        overrides = object.__getattribute__(self, '_overrides')
        if name in overrides:
            return overrides[name]
        return getattr(object.__getattribute__(self, '_real'), name)


class _InnerDailyTrifles(DailyTriflesScriptTask):
    def plan_next_dt(self):
        # 小号的每日琐事由轮换任务统一调度，不更新「每日琐事」独立任务的下次运行时间
        pass


class _InnerWeeklyTrifles(WeeklyTriflesScriptTask):
    def set_next_run(self, *args, **kwargs):
        # 同上，不更新「每周琐事」独立任务的下次运行时间
        pass


class _InnerAreaBoss(AreaBossScriptTask):
    def set_next_run(self, *args, **kwargs):
        # 地域鬼王由轮换任务统一调度，不更新「地域鬼王」独立任务的下次运行时间
        pass


class _InnerConsignment(ConsignmentMixin):
    """复用 RichMan 的寄售屋流程：进商店后执行 execute_consignment。

    RichMan 任务本身的调度不应开启（避免重复跑全套商店）；只读 rich_man.consignment 配置。
    """
    def run_consignment(self):
        self.goto_page(page_mall, confirm_wait=2.5)
        self.execute_consignment(self.config.rich_man.consignment)


class _InnerCooperationScan(WantedQuestsScriptTask):
    """复用悬赏封印任务的页面进入与协作识别资产：登录后只扫描协作类型，不邀请不追踪"""

    # 槽位类型识别顺序沿用悬赏任务（食物协作卡片上也有金币字样，金币放最后判断）
    _TYPE_LABELS = (
        ('JADE', '勾协'),
        ('DOG_FOOD', '食协'),
        ('CAT_FOOD', '食协'),
        ('SUSHI', '体协'),
        ('GOLD', '金币协'),
    )

    def scan(self):
        if self.get_current_page() != page_main:
            self.goto_page(page_main)
        # 打开悬赏封印界面，等追踪按钮出现即认为已打开（与悬赏任务协作模式同一套等待逻辑）
        done_timer = Timer(5)
        # 整体限时：红箭头超时只覆盖卡在其他页面的情况，庭院皮肤异常等也要保证轮换不空转
        open_timer = Timer(75).start()
        while 1:
            self.screenshot()
            if self.appear(self.I_TRACE_ENABLE) or self.appear(self.I_TRACE_DISABLE):
                break
            if open_timer.reached():
                logger.warning('[小号轮换] 打开悬赏封印超时，本账号本轮协作扫描跳过')
                self.ui_click_until_disappear(self.I_UI_BACK_RED)
                return None
            if self.appear_then_click(self.I_WQ_SEAL, interval=1):
                continue
            if self.appear_then_click(self.I_WQ_DONE, interval=1):
                continue
            if self.special_main and self.click(self.C_SPECIAL_MAIN, interval=3):
                logger.info('[小号轮换] 点击特殊庭院左侧以找到悬赏封印')
                continue
            if self.appear(self.I_UI_BACK_RED):
                if not done_timer.started():
                    done_timer.start()
            if done_timer.started() and done_timer.reached():
                self.ui_click_until_disappear(self.I_UI_BACK_RED)
                return None
        types = self.read_cooperation_types()
        self.ui_click_until_disappear(self.I_UI_BACK_RED)
        return types

    def read_cooperation_types(self):
        """按 3 个协作槽位识别类型；模板未覆盖的类型（如现世系协作）记为「未识别协作」"""
        self.screenshot()
        types = []
        for index in range(1, 4):
            if not self.appear(self.__getattribute__(f'I_WQ_INVITE_{index}')):
                break
            for asset_key, label in self._TYPE_LABELS:
                if self.appear(self.__getattribute__(f'I_WQ_COOPERATION_TYPE_{asset_key}_{index}')):
                    types.append(label)
                    break
            else:
                types.append('未识别协作')
        logger.info('[小号轮换] 协作任务数量: %d', len(types))
        return types


class ScriptTask(GameUi):

    def run(self):
        conf = self.config.alt_accounts
        settings = conf.alt_accounts_config
        had_error = False
        scan_results = []
        for accountInfo in conf.alt_account_list:
            if not accountInfo.is_valid():
                logger.warning('[小号轮换] 存在未填写角色名的小号条目，跳过')
                continue
            daily_due = settings.run_daily_trifles and self._daily_not_done(accountInfo)
            weekly_due = settings.run_weekly_trifles and self._weekly_due(accountInfo)
            area_due = settings.run_area_boss and self._area_boss_not_done(accountInfo)
            consignment_due = settings.run_consignment and self._consignment_due(accountInfo)
            scan_due = settings.run_cooperation_scan and self._cooperation_scan_due(accountInfo)
            if not daily_due and not weekly_due and not area_due and not consignment_due and not scan_due:
                logger.info('[小号轮换] %s-%s 今日任务已完成，跳过',
                            accountInfo.character, accountInfo.svr)
                continue
            logger.hr(f'小号轮换：{accountInfo.character}-{accountInfo.svr}', 2)
            try:
                suc = SwitchAccount(self.config, self.device, accountInfo).switchAccount()
            except RequestHumanTakeover:
                raise
            except Exception as e:
                logger.error('[小号轮换] 切换到 %s-%s 异常: %s',
                             accountInfo.character, accountInfo.svr, e)
                suc = False
            if not suc:
                logger.warning('[小号轮换] 切换到 %s-%s 失败，跳过该小号',
                               accountInfo.character, accountInfo.svr)
                had_error = True
                continue
            if scan_due:
                # 登录后先扫协作（悬赏协作会被好友陆续接受，越早扫越准）
                try:
                    types = _InnerCooperationScan(config=self.config, device=self.device).scan()
                except RequestHumanTakeover:
                    raise
                except Exception as e:
                    logger.error('[小号轮换] %s 协作扫描执行异常: %s', accountInfo.character, e)
                    types = None
                    had_error = True
                if types is None:
                    logger.warning('[小号轮换] %s 协作扫描未完成，下轮重试', accountInfo.character)
                else:
                    scan_results.append((f'{accountInfo.character}-{accountInfo.svr}', types))
                    logger.info('[小号轮换] %s 协作扫描完成: %s',
                                accountInfo.character, self._fmt_cooperation_types(types))
                    conf.update_account_complete_time(accountInfo, kind='scan')
            if daily_due:
                try:
                    self._run_daily_trifles()
                    logger.info('[小号轮换] %s 每日琐事完成', accountInfo.character)
                except RequestHumanTakeover:
                    raise
                except TaskEnd:
                    logger.info('[小号轮换] %s 每日琐事任务结束', accountInfo.character)
                except Exception as e:
                    logger.error('[小号轮换] %s 每日琐事执行异常: %s', accountInfo.character, e)
                    had_error = True
                conf.update_account_complete_time(accountInfo)
            if weekly_due:
                try:
                    self._run_weekly_trifles()
                    logger.info('[小号轮换] %s 每周琐事完成', accountInfo.character)
                except RequestHumanTakeover:
                    raise
                except TaskEnd:
                    logger.info('[小号轮换] %s 每周琐事任务结束', accountInfo.character)
                except Exception as e:
                    logger.error('[小号轮换] %s 每周琐事执行异常: %s', accountInfo.character, e)
                    had_error = True
                conf.update_account_complete_time(accountInfo, kind='weekly')
            if area_due:
                try:
                    self._run_area_boss()
                    logger.info('[小号轮换] %s 地域鬼王完成', accountInfo.character)
                except RequestHumanTakeover:
                    raise
                except TaskEnd:
                    logger.info('[小号轮换] %s 地域鬼王任务结束', accountInfo.character)
                except Exception as e:
                    logger.error('[小号轮换] %s 地域鬼王执行异常: %s', accountInfo.character, e)
                    had_error = True
                conf.update_account_complete_time(accountInfo, kind='area_boss')
            if consignment_due:
                try:
                    _InnerConsignment(config=self.config, device=self.device).run_consignment()
                    logger.info('[小号轮换] %s 寄售屋完成', accountInfo.character)
                except RequestHumanTakeover:
                    raise
                except TaskEnd:
                    logger.info('[小号轮换] %s 寄售屋任务结束', accountInfo.character)
                except Exception as e:
                    logger.error('[小号轮换] %s 寄售屋执行异常: %s', accountInfo.character, e)
                    had_error = True
                conf.update_account_complete_time(accountInfo, kind='consignment')
            self.config.save()
        if scan_results:
            self._push_cooperation_report(scan_results)
        # 全部跑完后按需切回主力角色，避免同配置的后续任务登录在小号上
        if settings.login_back_enable and settings.login_back_character:
            back_info = AccountInfo(character=settings.login_back_character)
            logger.hr('小号轮换：切回主力角色', 2)
            try:
                suc = SwitchAccount(self.config, self.device, back_info).switchAccount()
            except Exception as e:
                logger.error('[小号轮换] 切回角色 %s 异常: %s', settings.login_back_character, e)
                suc = False
            if not suc:
                logger.warning('[小号轮换] 切回角色 %s 失败', settings.login_back_character)
        self._set_next_run(success=not had_error)
        raise TaskEnd('AltAccounts')

    def _set_next_run(self, success: bool):
        """定时模式按 1~2 个每日固定时间点取最近的一个；关闭时保持默认成功/失败间隔调度。
        失败时 task_delay 会取「失败间隔」与固定时间点中更近者，保留 30 分钟重试语义"""
        sch = self.config.alt_accounts.scheduler
        if not sch.fixed_time_enable:
            self.set_next_run(task='AltAccounts', success=success)
            return
        now = datetime.now()
        targets = []
        for t in (sch.fixed_time_1, sch.fixed_time_2):
            if t.hour == 0 and t.minute == 0 and t.second == 0:
                continue  # 0 点的时间点视为未启用
            cand = now.replace(hour=t.hour, minute=t.minute, second=t.second, microsecond=0)
            if cand <= now:
                cand += timedelta(days=1)
            targets.append(cand)
        if not targets:
            logger.warning('[小号轮换] 定时模式未填有效时间点，退回默认间隔调度')
            self.set_next_run(task='AltAccounts', success=success)
            return
        target = min(targets)
        # 与默认调度一致：按浮动时间加随机延迟模拟人工，并保证落在将来
        float_seconds = (sch.float_time.hour * 3600 +
                         sch.float_time.minute * 60 + sch.float_time.second)
        if float_seconds:
            target += timedelta(seconds=random.randint(0, float_seconds))
        if target <= now + timedelta(seconds=120):
            target = now + timedelta(seconds=120)
        self.set_next_run(task='AltAccounts', success=success, server=False, target=target)

    @staticmethod
    def _fmt_cooperation_types(types: list, markdown: bool = False) -> str:
        if not types:
            return '<font color="comment">无协作</font>' if markdown else '无协作'
        counter = {}
        for t in types:
            counter[t] = counter.get(t, 0) + 1
        parts = []
        for k, v in counter.items():
            label = f'{k}×{v}' if v > 1 else k
            if markdown:
                # 企业微信 markdown 仅 info/comment/warning 三色：按用户约定只给勾协黄色、体协绿色，未识别灰色，其余类型不着色
                if k == '勾协':
                    label = f'<font color="warning">{label}</font>'
                elif k == '体协':
                    label = f'<font color="info">{label}</font>'
                elif k == '未识别协作':
                    label = f'<font color="comment">{label}</font>'
            parts.append(label)
        return '、'.join(parts)

    def _cooperation_scan_due(self, accountInfo: AccountInfo) -> bool:
        """悬赏协作 5 点/18 点各刷新一次：上次扫描早于最近一个刷新点就需要重扫"""
        now = datetime.now()
        today5 = now.replace(hour=5, minute=0, second=0, microsecond=0)
        today18 = now.replace(hour=18, minute=0, second=0, microsecond=0)
        if now >= today18:
            ref = today18
        elif now >= today5:
            ref = today5
        else:
            ref = today18 - timedelta(days=1)
        return accountInfo.cooperation_scan_time < ref

    def _push_cooperation_report(self, scan_results):
        """扫描完成后推送汇总；开关关闭、渠道未配置或推送失败都不影响任务本身"""
        settings = self.config.alt_accounts.alt_accounts_config
        if not settings.cooperation_notify_enable:
            return
        notifier = Notifier(settings.cooperation_notify_config, enable=True)
        notifier.config_name = self.config.config_name
        markdown = getattr(notifier, 'provider_name', None) == 'wechatworkbot'
        # 有勾协的账号排最前，其余有协作的次之，无协作垫底
        ordered = sorted(scan_results,
                         key=lambda item: 0 if '勾协' in item[1] else (1 if item[1] else 2))
        blocks = [f'扫描时间: {datetime.now().strftime("%H:%M")}']
        blocks += [f'{name}: {self._fmt_cooperation_types(types, markdown)}'
                   for name, types in ordered]
        content = '\n'.join(blocks)
        try:
            notifier.push(title='小号协作扫描', content=content, markdown=markdown)
            logger.info('[小号轮换] 协作扫描汇总已推送')
        except Exception:
            logger.exception('[小号轮换] 协作扫描推送失败')

    def _daily_not_done(self, accountInfo: AccountInfo) -> bool:
        """本小号今天是否还没跑过每日琐事"""
        return accountInfo.last_complete_time.date() != datetime.now().date()

    def _weekly_due(self, accountInfo: AccountInfo) -> bool:
        """每周琐事：本自然周未完成且已到锚定星期（默认周一，错过则本周内补跑）"""
        return self._weekly_anchor_due(accountInfo.weekly_complete_time)

    def _consignment_due(self, accountInfo: AccountInfo) -> bool:
        """寄售屋：与每周琐事同周期，本自然周未完成且已到锚定星期才购买"""
        return self._weekly_anchor_due(accountInfo.consignment_complete_time)

    def _weekly_anchor_due(self, complete_time) -> bool:
        now = datetime.now()
        if complete_time.isocalendar()[:2] == now.isocalendar()[:2]:
            return False
        anchor = self.config.alt_accounts.alt_accounts_config.weekly_anchor_weekday
        return now.weekday() >= anchor

    def _area_boss_not_done(self, accountInfo: AccountInfo) -> bool:
        """本小号今天是否还没打过地域鬼王；0-6 点鬼王未刷新不可挑战"""
        if dt_time(0, 0) <= datetime.now().time() <= dt_time(6, 0):
            return False
        return accountInfo.area_boss_complete_time.date() != datetime.now().date()

    def _run_daily_trifles(self):
        """以独立配置节运行每日琐事：每个小号各自重置当日完成记录"""
        section = self.config.daily_trifles.model_copy(deep=True)
        section.done_record = DoneRecord()
        proxy = _ConfigSectionProxy(self.config, {'daily_trifles': section})
        _InnerDailyTrifles(config=proxy, device=self.device).run()

    def _run_weekly_trifles(self):
        """以独立配置节运行每周琐事"""
        section = self.config.weekly_trifles.model_copy(deep=True)
        proxy = _ConfigSectionProxy(self.config, {'weekly_trifles': section})
        _InnerWeeklyTrifles(config=proxy, device=self.device).run()

    def _run_area_boss(self):
        """以独立配置节运行地域鬼王（挑战设置用「地域鬼王」配置页）"""
        section = self.config.area_boss.model_copy(deep=True)
        proxy = _ConfigSectionProxy(self.config, {'area_boss': section})
        _InnerAreaBoss(config=proxy, device=self.device).run()


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)
    t.run()
