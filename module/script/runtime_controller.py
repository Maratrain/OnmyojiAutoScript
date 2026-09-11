# This Python file uses the following encoding: utf-8

from datetime import datetime, timedelta
from enum import Enum
from module.exception import RequestHumanTakeover, GameNotRunningError
from typing import Any, Callable, Protocol

from module.device.device import Device
from module.device.platform2 import Platform
from module.logger import logger


class ScriptRuntimeOwner(Protocol):
    """
    运行时控制器依赖的最小调度器接口。
    """
    config: Any
    device: Device
    _emulator_down: bool
    last_task_runtime_outcome: dict[str, Any] | None
    __dict__: dict[str, Any]

    def wait_until(self, future: datetime) -> bool:
        """
        等待到指定时间，返回等待是否完整结束。
        """

    def run(self, command: str) -> bool:
        """
        执行指定任务命令。
        """


class ScriptRuntimeDecision(str, Enum):
    """
    运行时控制器对当前分支给出的调度决策。
    """
    READY = 'ready'
    RESCHEDULE = 'reschedule'
    FAILED = 'failed'


class ScriptRuntimeController:
    """
    负责调度器运行环境保障，包括空闲策略、模拟器预热与游戏状态修正。
    """

    def __init__(self, script: ScriptRuntimeOwner) -> None:
        """
        Args:
            script: 调度器对象，提供运行时所需的配置、设备与等待接口。
        """
        self.script = script
        self.server_update_wait_until: datetime | None = None
        self.server_update_wait_log_until: datetime | None = None
        # 等待窗口的原因标注，用于日志区分「停服」与「页面识别退避」等场景
        self.server_update_wait_reason: str = '停服'

    @property
    def config(self):
        return self.script.config

    @property
    def device(self) -> Device:
        return self.script.device

    @property
    def emulator_down(self) -> bool:
        return self.script._emulator_down

    @emulator_down.setter
    def emulator_down(self, value: bool) -> None:
        self.script._emulator_down = value

    @staticmethod
    def _format_datetime(value: datetime | None) -> str:
        if value is None:
            return 'None'
        return value.strftime('%Y-%m-%d %H:%M:%S')

    def _clear_server_update_wait_if_expired(self) -> None:
        if self.server_update_wait_until is None:
            return
        if datetime.now() >= self.server_update_wait_until:
            logger.info(
                f'[脚本控制] {self.server_update_wait_reason}等待窗口已于 '
                f'{self._format_datetime(self.server_update_wait_until)} 结束，恢复正常恢复流程'
            )
            self.server_update_wait_until = None
            self.server_update_wait_log_until = None
            self.server_update_wait_reason = '停服'

    def _is_server_update_wait_active(self) -> bool:
        self._clear_server_update_wait_if_expired()
        return self.server_update_wait_until is not None

    def _wait_for_server_update_window(self, context: str) -> ScriptRuntimeDecision:
        """
        在停服等待窗口内安静等待到边界，避免反复重调度和重复拉起环境。

        Args:
            context: 当前等待发生的上下文，用于中断日志。

        Returns:
            ScriptRuntimeDecision: 等待后的调度决策。
        """
        if not self._is_server_update_wait_active():
            return ScriptRuntimeDecision.READY

        wait_until = self.server_update_wait_until
        if wait_until is None:
            return ScriptRuntimeDecision.READY

        if self.server_update_wait_log_until != wait_until:
            logger.info(
                f'[脚本控制] {self.server_update_wait_reason}等待窗口持续至 '
                f'{self._format_datetime(wait_until)}，在此之前暂停运行时操作'
            )
            self.server_update_wait_log_until = wait_until

        if not self.script.wait_until(wait_until):
            logger.info(f'[脚本控制] 停服等待在 {context} 期间被配置重载中断，重新调度')
            return ScriptRuntimeDecision.RESCHEDULE

        self._clear_server_update_wait_if_expired()
        return ScriptRuntimeDecision.READY

    def _get_runtime_outcome(self) -> dict[str, Any] | None:
        outcome = getattr(self.script, 'last_task_runtime_outcome', None)
        if not isinstance(outcome, dict):
            return None
        return outcome

    def _consume_server_update_delay_outcome(self, source: str) -> ScriptRuntimeDecision | None:
        outcome = self._get_runtime_outcome()
        if outcome is None or outcome.get('status') != 'server_update_delayed':
            return None

        wait_until = outcome.get('wait_until')
        if isinstance(wait_until, datetime):
            self.server_update_wait_until = wait_until
            self.server_update_wait_log_until = None
        logger.info(
            f'[脚本控制] {source} 因停服延迟，'
            f'重新调度并等待至 {self._format_datetime(self.server_update_wait_until)}'
        )
        return ScriptRuntimeDecision.RESCHEDULE

    @staticmethod
    def _time_to_timedelta(value) -> timedelta:
        """
        将配置中的时间对象转换为 `timedelta`。

        Args:
            value: 配置中的时间对象，允许为 None。

        Returns:
            timedelta: 转换后的时间间隔；当 value 为 None 时返回 0。
        """
        if value is None:
            return timedelta(0)
        return timedelta(hours=value.hour, minutes=value.minute, seconds=value.second)

    def _build_platform_probe(self) -> Platform:
        """
        构造一个仅用于探测目标模拟器状态的平台对象。

        Returns:
            Platform: 已注入当前配置和目标 serial 的平台探测对象。
        """
        probe = Platform()
        probe.config = self.config
        probe.serial = str(self.config.script.device.serial)
        return probe

    def _sync_emulator_down_state_on_startup(self) -> None:
        """
        在脚本尚未初始化 `device` 时，同步一次模拟器真实状态。

        仅用于关闭模拟器相关策略，避免在“模拟器本来就关闭”的情况下，
        因为访问 `self.device` 而触发 `Device` 初始化，反而把模拟器先拉起来。
        """
        if self.emulator_down or 'device' in self.script.__dict__:
            return

        try:
            online = self._build_platform_probe().probe_target_instance_online()
        except Exception as e:
            logger.info(f'[脚本控制] 探测目标模拟器失败：{e}')
            return

        if online is False:
            logger.info('[脚本控制] 目标模拟器已处于关闭状态，保持等待不拉起')
            self.emulator_down = True

    def _ensure_emulator_running(self, reason: str | None = None) -> None:
        """
        确保模拟器处于启动状态。

        Args:
            reason: 当需要拉起模拟器时输出到日志的原因说明。
        """
        if self.emulator_down:
            if reason:
                logger.info(reason)
            self.script.device = Device(self.config)
            self.emulator_down = False
            return

        _ = self.device

    def _run_restart_recovery(self, reason: str) -> ScriptRuntimeDecision:
        """
        通过 `Restart` 任务恢复游戏运行环境。

        Args:
            reason: 触发恢复的原因说明。

        Returns:
            ScriptRuntimeDecision:
                `RESCHEDULE` 表示恢复成功但需要回到主调度器重新选任务，
                `FAILED` 表示恢复失败。
        """
        logger.info(reason)
        if not self.script.run('Restart'):
            logger.warning('[脚本控制] 运行时恢复期间 Restart 任务失败')
            return ScriptRuntimeDecision.FAILED

        decision = self._consume_server_update_delay_outcome('Restart 恢复')
        if decision is not None:
            return decision

        self.server_update_wait_until = None
        self.server_update_wait_log_until = None

        if not self.device.app_is_running():
            logger.warning('[脚本控制] Restart 恢复后游戏仍未运行')
            return ScriptRuntimeDecision.FAILED

        logger.info('[脚本控制] Restart 恢复完成，重新调度后继续')
        return ScriptRuntimeDecision.RESCHEDULE

    def _ensure_game_running(
        self,
        require_main: bool = False,
        allow_server_update_skip: bool = False
    ) -> ScriptRuntimeDecision:
        """
        确保模拟器和游戏都处于运行状态。

        Args:
            require_main: 是否要求额外回到游戏主界面。
            allow_server_update_skip: 是否允许在停服等待窗口内跳过本轮恢复。

        Returns:
            ScriptRuntimeDecision: 当前分支后续应如何处理。
        """
        if allow_server_update_skip:
            wait_decision = self._wait_for_server_update_window('idle preparation')
            if wait_decision is not ScriptRuntimeDecision.READY:
                return wait_decision

        self._ensure_emulator_running('任务前拉起模拟器，确保游戏状态')

        if not self.device.app_is_running():
            return self._run_restart_recovery('游戏未运行，通过 Restart 恢复')

        if require_main:
            logger.info('[脚本控制] 等待期间确保游戏停留在主界面')
            if self.script.run('GotoMain'):
                return ScriptRuntimeDecision.READY
            decision = self._consume_server_update_delay_outcome('GotoMain preparation')
            if decision is not None:
                return decision
            logger.warning('[脚本控制] 空闲准备期间 GotoMain 失败')
            return ScriptRuntimeDecision.FAILED

        return ScriptRuntimeDecision.READY

    def _ensure_game_closed(self) -> ScriptRuntimeDecision:
        """
        确保模拟器已启动，但游戏处于关闭状态。
        """
        self._ensure_emulator_running('close_game 前拉起模拟器，确保游戏状态')
        if self.device.app_is_running():
            logger.info('[脚本控制] 等待期间确保游戏已关闭')
            self.device.app_stop()
            return ScriptRuntimeDecision.READY

        logger.info('[脚本控制] 等待期间游戏已处于关闭状态')
        return ScriptRuntimeDecision.READY

    def _prepare_idle_goto_main(self) -> ScriptRuntimeDecision:
        """
        将空闲状态调整为“模拟器开启、游戏运行且位于主界面”。
        停服窗口内改为关闭游戏，避免停留在停服弹窗。
        """
        if self._is_server_update_wait_active():
            logger.info('[脚本控制] 停服期间生效，关闭游戏而不前往主界面')
            return self._ensure_game_closed()
        return self._ensure_game_running(require_main=True, allow_server_update_skip=True)

    def _prepare_idle_close_game(self) -> ScriptRuntimeDecision:
        """
        将空闲状态调整为“模拟器开启、游戏关闭”。
        """
        return self._ensure_game_closed()

    def _prepare_idle_keep_game_running(self) -> ScriptRuntimeDecision:
        """
        将空闲状态调整为“模拟器开启、游戏运行”。
        """
        return self._ensure_game_running(require_main=False, allow_server_update_skip=True)

    def prepare_task_execution(self, task: str) -> ScriptRuntimeDecision:
        """
        在任务真正执行前补齐运行环境。

        Args:
            task: 即将执行的任务名，使用调度器中的下划线命名。

        Returns:
            ScriptRuntimeDecision: 当前轮次应继续执行、重新调度或中断。
        """
        if task == 'Restart':
            return ScriptRuntimeDecision.READY

        wait_decision = self._wait_for_server_update_window(f'task `{task}` preparation')
        if wait_decision is not ScriptRuntimeDecision.READY:
            return wait_decision

        self._ensure_emulator_running('任务运行前拉起模拟器')

        try:
            running = self.device.app_is_running()
        except RequestHumanTakeover as e:
            # adb 重试 3 次都连不上 → "无法确认游戏是否在前台"。
            # 翻译为 GameNotRunningError,沿调用栈上抛,
            # 由 Script._handle_task_exception 统一走 Restart 恢复分支。
            raise GameNotRunningError(f'任务 `{task}` 运行前查询应用状态失败（可能是 ADB 掉线）: {e}') \
                from e

        if not running:
            return self._run_restart_recovery(f'任务 `{task}` 运行前游戏未运行，通过 Restart 恢复')

        return ScriptRuntimeDecision.READY

    def _wait_until_with_emulator_preheat(
        self,
        next_run: datetime,
        on_wake: Callable[[], ScriptRuntimeDecision] | None = None
    ) -> ScriptRuntimeDecision:
        """
        在等待下个任务期间处理模拟器预热。

        Args:
            next_run: 下一个任务的计划运行时间。
            on_wake: 模拟器被提前拉起后需要立即执行的状态修正动作。

        Returns:
            ScriptRuntimeDecision: 当前等待分支的处理结果。
        """
        startup_lead = self._time_to_timedelta(self.config.script.optimization.emulator_startup_lead_time)

        while self.emulator_down:
            wait_decision = self._wait_for_server_update_window('idle emulator preheat')
            if wait_decision is not ScriptRuntimeDecision.READY:
                return wait_decision

            now = datetime.now()
            wake_time = next_run - startup_lead if startup_lead > timedelta(0) else next_run
            if wake_time > now:
                logger.info(f'[脚本控制] 等待预热模拟器: {wake_time.strftime("%Y-%m-%d %H:%M:%S")}')
                if not self.script.wait_until(wake_time):
                    logger.info('[脚本控制] 空闲等待在模拟器预热前被中断，重新调度')
                    return ScriptRuntimeDecision.RESCHEDULE
                continue

            logger.info('[脚本控制] 在下个任务前预热模拟器')
            self._ensure_emulator_running()
            if on_wake is not None:
                decision = on_wake()
                if decision is not ScriptRuntimeDecision.READY:
                    return decision
            break

        if datetime.now() < next_run:
            if not self.script.wait_until(next_run):
                logger.info('[脚本控制] 空闲等待在模拟器预热后被中断，重新调度')
                return ScriptRuntimeDecision.RESCHEDULE
        return ScriptRuntimeDecision.READY

    def _should_close_game_during_wait(self, next_run: datetime) -> bool:
        """
        判断本次空闲等待是否需要关闭游戏。

        Args:
            next_run: 下一个任务的计划运行时间。

        Returns:
            bool: True 表示本次等待前应关闭游戏；False 表示保持当前状态直接等待。
        """
        close_game_limit_time = self.config.script.optimization.close_game_limit_time
        close_game_limit = self._time_to_timedelta(close_game_limit_time)

        if close_game_limit <= timedelta(0):
            logger.info('[脚本控制] 等待期间立即关闭游戏（close_game_limit_time <= 0）')
            return True

        if next_run > datetime.now() + close_game_limit:
            logger.info('[脚本控制] 等待期间关闭游戏（下个任务超出 close_game_limit_time）')
            return True

        logger.info('[脚本控制] 短时等待期间保持游戏运行（下个任务在 close_game_limit_time 内）')
        return False

    def _wait_close_game(self, next_run: datetime) -> ScriptRuntimeDecision:
        """
        按“关闭游戏”策略等待下个任务。

        Args:
            next_run: 下一个任务的计划运行时间。

        Returns:
            ScriptRuntimeDecision: 当前等待分支的处理结果。
        """
        if self._should_close_game_during_wait(next_run):
            decision = self._prepare_idle_close_game()
            if decision is not ScriptRuntimeDecision.READY:
                return decision
            self.device.release_during_wait()
            if not self.script.wait_until(next_run):
                logger.info('[脚本控制] 关闭游戏的空闲等待被配置重载中断，重新调度')
                return ScriptRuntimeDecision.RESCHEDULE
            return ScriptRuntimeDecision.READY

        decision = self._prepare_idle_keep_game_running()
        if decision is not ScriptRuntimeDecision.READY:
            return decision
        self.device.release_during_wait()
        if not self.script.wait_until(next_run):
            logger.info('[脚本控制] 保持游戏运行的短时空闲等待被配置重载中断，重新调度')
            return ScriptRuntimeDecision.RESCHEDULE
        return ScriptRuntimeDecision.READY

    def _wait_goto_main(self, next_run: datetime) -> ScriptRuntimeDecision:
        """
        按“前往主界面”策略等待下个任务。

        Args:
            next_run: 下一个任务的计划运行时间。

        Returns:
            ScriptRuntimeDecision: 当前等待分支的处理结果。
        """
        decision = self._prepare_idle_goto_main()
        if decision is not ScriptRuntimeDecision.READY:
            return decision
        self.device.release_during_wait()
        if not self.script.wait_until(next_run):
            logger.info('[脚本控制] 前往主界面的空闲等待被配置重载中断，重新调度')
            return ScriptRuntimeDecision.RESCHEDULE
        return ScriptRuntimeDecision.READY

    def _wait_close_emulator_or_goto_main(self, next_run: datetime) -> ScriptRuntimeDecision:
        """
        按“关闭模拟器&前往主界面”策略等待下个任务。

        Args:
            next_run: 下一个任务的计划运行时间。

        Returns:
            ScriptRuntimeDecision: 当前等待分支的处理结果。
        """
        return self._wait_close_emulator_or(
            next_run,
            fallback_waiter=self._wait_goto_main,
            on_wake=self._prepare_idle_goto_main,
        )

    def _wait_close_emulator_or_close_game(self, next_run: datetime) -> ScriptRuntimeDecision:
        """
        按“关闭模拟器&关闭游戏”策略等待下个任务。

        Args:
            next_run: 下一个任务的计划运行时间。

        Returns:
            ScriptRuntimeDecision: 当前等待分支的处理结果。
        """
        return self._wait_close_emulator_or(
            next_run,
            fallback_waiter=self._wait_close_game,
            on_wake=self._prepare_idle_close_game,
        )

    def _wait_close_emulator_or(
        self,
        next_run: datetime,
        fallback_waiter: Callable[[datetime], ScriptRuntimeDecision],
        on_wake: Callable[[], ScriptRuntimeDecision]
    ) -> ScriptRuntimeDecision:
        """
        处理带“关闭模拟器”语义的空闲等待策略。

        Args:
            next_run: 下一个任务的计划运行时间。
            fallback_waiter: 未达到关模拟器阈值时使用的等待策略。
            on_wake: 模拟器预热完成后需要恢复到的目标状态动作。

        Returns:
            ScriptRuntimeDecision: 当前等待分支的处理结果。
        """
        self._sync_emulator_down_state_on_startup()

        close_emulator_limit_time = self.config.script.optimization.close_emulator_limit_time
        close_emulator_limit = self._time_to_timedelta(close_emulator_limit_time)

        if self.emulator_down:
            logger.info('[脚本控制] 模拟器已关闭，保持 close_emulator 策略并带预热等待')
            return self._wait_until_with_emulator_preheat(next_run, on_wake=on_wake)

        if close_emulator_limit > timedelta(0) and next_run > datetime.now() + close_emulator_limit:
            logger.info('[脚本控制] 等待期间关闭模拟器')
            self.device.emulator_stop()
            self.emulator_down = True
            return self._wait_until_with_emulator_preheat(next_run, on_wake=on_wake)

        return fallback_waiter(next_run)

    def _wait_stay_there(self, next_run: datetime) -> ScriptRuntimeDecision:
        """
        按“保持现状”策略等待下个任务。

        Args:
            next_run: 下一个任务的计划运行时间。

        Returns:
            ScriptRuntimeDecision: 当前等待分支的处理结果。
        """
        if self.emulator_down:
            logger.info('[脚本控制] 等待期间执行 stay_there（模拟器已关闭，带预热）')
            return self._wait_until_with_emulator_preheat(next_run)

        logger.info('[脚本控制] 等待期间执行 stay_there（无操作）')
        self.device.release_during_wait()
        if not self.script.wait_until(next_run):
            logger.info('[脚本控制] stay_there 空闲等待被配置重载中断，重新调度')
            return ScriptRuntimeDecision.RESCHEDULE
        return ScriptRuntimeDecision.READY

    def handle_wait_during_idle(self, next_run: datetime) -> ScriptRuntimeDecision:
        """
        处理任务空闲期间的行为策略。

        Args:
            next_run: 下一个任务的计划运行时间。

        Returns:
            ScriptRuntimeDecision: 当前等待分支的处理结果。
        """
        method = self.config.script.optimization.when_task_queue_empty
        strategy_map = {
            'close_game': self._wait_close_game,
            'goto_main': self._wait_goto_main,
            'close_emulator_or_goto_main': self._wait_close_emulator_or_goto_main,
            'close_emulator_or_close_game': self._wait_close_emulator_or_close_game,
        }
        func = strategy_map.get(method)
        if func is None:
            logger.warning(f'[脚本控制] 非法的 Optimization_WhenTaskQueueEmpty: {method}，回退到 stay_there')
            func = self._wait_stay_there
        return func(next_run)
