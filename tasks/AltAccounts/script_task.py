# This Python file uses the following encoding: utf-8
# 小号轮换：同一账号下不同区服的角色逐个登录，执行每日琐事/每周琐事后切换下一个
from datetime import datetime, timedelta

from module.exception import TaskEnd, RequestHumanTakeover
from module.logger import logger

from tasks.Component.SwitchAccount.switch_account import SwitchAccount
from tasks.Component.SwitchAccount.switch_account_config import AccountInfo
from tasks.DailyTrifles.config import DoneRecord
from tasks.DailyTrifles.script_task import ScriptTask as DailyTriflesScriptTask
from tasks.WeeklyTrifles.script_task import ScriptTask as WeeklyTriflesScriptTask
from tasks.GameUi.game_ui import GameUi


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
            if not daily_due and not weekly_due:
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
                conf.update_account_complete_time(accountInfo, weekly=True)
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
        """距上次完成每周琐事是否已满 6 天（不固定周几，停机错过也不漏）"""
        return datetime.now() - accountInfo.weekly_complete_time >= timedelta(days=6)

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


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)
    t.run()
