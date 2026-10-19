# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from datetime import datetime

from module.exception import (RequestHumanTakeover,
                              TaskEnd,
                              GameNotRunningError,
                              GameStuckError,
                              GameTooManyClickError)
from module.logger import logger
from tasks.Component.Login.service import LoginService
from tasks.Restart.server_update import delay_pending_tasks_for_server_update, is_server_update_window
from tasks.base_task import BaseTask

# 桌面客户端「启动+登录」的就地重试轮数：Restart 就是负责启动客户端的任务，
# 起不来必须自己扛住，抛给调度器会形成无限重启循环
DESKTOP_RESTART_ATTEMPTS = 3


class ScriptTask(BaseTask):
    def _set_runtime_outcome(self, status: str, wait_until: datetime | None = None) -> None:
        outcome = {
            'task': 'Restart',
            'status': status,
        }
        if wait_until is not None:
            outcome['wait_until'] = wait_until
        self.config.task_runtime_outcome = outcome

    def run(self) -> None:
        """
        主要就是登录的模块
        :return:
        """
        try:
            self.recover_app()
            self.finish_recovery()
        except RequestHumanTakeover:
            if not self.delay_pending_tasks(reason='login failed during Restart recovery'):
                raise
        raise TaskEnd

    def app_stop(self):
        logger.hr('停止应用')
        self.device.app_stop()

    def app_start(self):
        logger.hr('启动应用')
        if self.device.is_desktop:
            self._desktop_start_and_login()
            return
        self.device.app_start()
        self.device.wait_app_start_ready()
        LoginService(config=self.config, device=self.device).app_handle_login()

    def app_restart(self):
        logger.hr('重启应用')
        if self.device.is_desktop:
            # 客户端可能刚被自动拉起（停在登录页），先停再起会白关一次
            self._desktop_start_and_login()
        else:
            self.device.app_stop()
            self.app_start()

    def recover_app(self):
        if not self.device.app_is_alive():
            logger.info('[重启] 恢复分支: 游戏进程未运行且不在前台 -> 完整重启')
            self.app_restart()
            return

        if self.device.app_is_running():
            logger.info('[重启] 恢复分支: 游戏进程运行中且在前台 -> 完整重启')
            self.app_restart()
            return

        logger.info('[重启] 恢复分支: 游戏进程运行中但在后台 -> 切换到前台')
        self.app_start()

    def finish_recovery(self):
        self.set_next_run(task='Restart', success=True, finish=True, server=True)
        if self.config.model.restart.restart_config.enable_daily:
            self.config.task_call('DailyTrifles')
        self._set_runtime_outcome(status='recovered')

    def _desktop_start_and_login(self) -> None:
        """桌面模式：拉起客户端并登录，客户端窗口丢失时就地重拉，不把异常抛给调度器。

        Restart 就是负责启动客户端的任务：GameNotRunningError 抛出去会被 script.py
        接住再 task_call('Restart')，形成无限重启循环（每轮日志都「正常」，比直接崩
        更难排查），所以必须在这里就地消化。登录流程自身的失败重试由 app_handle_login
        内部完成（它会关掉客户端再重拉），这里只补「客户端窗口丢失」这一类重拉。
        """
        for attempt in range(1, DESKTOP_RESTART_ATTEMPTS + 1):
            try:
                self.device.app_start()
                LoginService(config=self.config, device=self.device).app_handle_login()
                return
            except (GameNotRunningError, GameStuckError, GameTooManyClickError) as e:
                logger.warning(f'[重启] 桌面客户端启动后仍未就绪（第 {attempt}/{DESKTOP_RESTART_ATTEMPTS} 轮）: {e}')
                # 每轮失败都清掉本轮客户端，否则残留窗口会干扰下一轮的新窗口识别
                logger.info('[重启] 清理本轮残留客户端')
                if not self.device.desktop_stop_client():
                    # 关不掉就别重建：残留窗口会让下一轮绑错句柄，越试越乱
                    logger.critical('[重启] 桌面客户端无法关闭，残留进程会干扰重建，请手动结束该进程')
                    raise RequestHumanTakeover
        logger.critical(f'[重启] 桌面客户端连续 {DESKTOP_RESTART_ATTEMPTS} 轮启动失败，请检查客户端与机器状态')
        raise RequestHumanTakeover

    def delay_pending_tasks(self, reason: str) -> bool:
        """
        仅在早间登录失败时，统一延后待执行任务。
        @return:
        """
        if not is_server_update_window():
            return False
        delay_target = delay_pending_tasks_for_server_update(self.config, reason=reason)
        self._set_runtime_outcome(status='server_update_delayed', wait_until=delay_target)
        return True


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    config = Config('oas1')
    device = Device(config)
    task = ScriptTask(config, device)
    task.app_restart()
