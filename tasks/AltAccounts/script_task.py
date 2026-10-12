# This Python file uses the following encoding: utf-8
# 小号轮换：同一账号下不同区服的角色逐个登录，执行每日琐事/每周琐事后切换下一个
from datetime import datetime, time as dt_time

from module.exception import TaskEnd, RequestHumanTakeover
from module.logger import logger

from tasks.AreaBoss.script_task import ScriptTask as AreaBossScriptTask
from tasks.Component.SwitchAccount.switch_account import SwitchAccount
from tasks.Component.SwitchAccount.switch_account_config import AccountInfo
from tasks.DailyTrifles.config import DoneRecord
from tasks.DailyTrifles.script_task import ScriptTask as DailyTriflesScriptTask
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main, page_mall
from tasks.RichMan.mall.consignment import Consignment as ConsignmentMixin
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


class ScriptTask(GameUi):

    def run(self):
        conf = self.config.alt_accounts
        settings = conf.alt_accounts_config
        had_error = False
        for accountInfo in conf.alt_account_list:
            if not accountInfo.is_valid():
                logger.warning('[小号轮换] 存在未填写角色名的小号条目，跳过')
                continue
            daily_due = settings.run_daily_trifles and self._daily_not_done(accountInfo)
            weekly_due = settings.run_weekly_trifles and self._weekly_due(accountInfo)
            area_due = settings.run_area_boss and self._area_boss_not_done(accountInfo)
            consignment_due = settings.run_consignment and self._consignment_due(accountInfo)
            if not daily_due and not weekly_due and not area_due and not consignment_due:
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
        self.set_next_run(task='AltAccounts', success=not had_error)
        raise TaskEnd('AltAccounts')

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
