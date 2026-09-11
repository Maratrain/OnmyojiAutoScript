# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey

import zerorpc
import zmq
import re
import cv2
import time
import os
import inflection
import json
import copy
import random

from datetime import date
import threading
from module.device.device import Device
from typing import Any, Callable
from datetime import datetime, timedelta
from pathlib import Path
from cached_property import cached_property
from pydantic import BaseModel, ValidationError
from threading import Thread
from multiprocessing.queues import Queue
from module.config.utils import convert_to_underscore
from module.atom.scatter import RuleScatter
from module.config.config import Config
from module.config.anti_ban import AntiBanGuard
from module.device.device import Device
from module.device.env import IS_WINDOWS
from module.base.utils import load_module
from module.base.decorator import del_cached_property
from module.logger import logger
from module.exception import *
from module.server.i18n import I18n
from module.image.rpc import ensure_image_server_ready, set_image_low_spec_mode
from module.ocr.rpc import ensure_ocr_server_ready, set_ocr_low_spec_mode, get_ocr_client
from module.script import ScriptRuntimeController, ScriptRuntimeDecision
from tasks.Restart.server_update import delay_pending_tasks_for_server_update, is_server_update_window
from module.server.log_service import build_error_log_dir_name

_log_switch_lock = threading.Lock()#线程锁

# 页面识别连续失败退避参数：统计窗口内失败达到阈值后，进入递增时长的安静等待
PAGE_UNKNOWN_FAIL_WINDOW = timedelta(minutes=30)
PAGE_UNKNOWN_FAIL_LIMIT = 3
PAGE_UNKNOWN_BACKOFF_BASE = timedelta(minutes=30)
PAGE_UNKNOWN_BACKOFF_CAP = timedelta(hours=2)


class Script:
    def __init__(self, config_name: str ='oas') -> None:
        logger.hr('启动', level=0)
        self.server = None
        self.state_queue: Queue = None
        self._emulator_down = False
        self.runtime = ScriptRuntimeController(self)
        self.gui_update_task: Callable = None  # 回调函数, gui进程注册当每次config更新任务的时候更新gui的信息
        self.config_name = config_name
        # Skip first restart
        self.is_first_task = True
        # Failure count of tasks
        # Key: str, task name, value: int, failure count
        self.failure_record = {}
        self.last_task_runtime_outcome: dict[str, Any] | None = None
        self.task_hoarding_until: datetime | None = None
        self.task_hoarding_released = False
        # 连续任务休息只统计调度器未进入等待状态的墙钟时间。
        self._continuous_task_started_at: float | None = None
        self._continuous_task_limit_seconds: int | None = None
        self._continuous_task_interval_range: tuple[int, int] | None = None
        # 低配模式属于进程级运行参数，只在脚本进程创建时读取一次。
        # OASX 中途修改配置不会影响正在运行的脚本。
        self.low_spec_mode = bool(self.config.script.device.low_spec_mode)
        set_image_low_spec_mode(self.low_spec_mode)
        set_ocr_low_spec_mode(self.low_spec_mode)
        if self.low_spec_mode:
            logger.info('[脚本] 低配模式已启用: 帧缓存=10秒, OCR超时=30秒, OCR结果缓存=2秒')
        self.resource_precache_enable = bool(
            self.config.script.device.resource_precache_enable
        )
        # 运行loop的线程
        self.loop_thread: Thread = None
        self.anti_ban_guard: AntiBanGuard = AntiBanGuard()
        # 页面识别连续失败退避状态（仅进程内使用）
        self._page_unknown_fail_times: list[datetime] = []
        self._page_unknown_backoff_round = 0

    @cached_property
    def config(self) -> "Config":
        try:
            from module.config.config import Config
            config = Config(config_name=self.config_name)
            return config
        except RequestHumanTakeover:
            logger.critical('[脚本] 请求人工接管')
            exit(1)
        except Exception as e:
            logger.exception(e)
            exit(1)

    @cached_property
    def device(self) -> Device | None:
        try:
            from module.device.device import Device
            device = Device(config=self.config)
            return device
        except RequestHumanTakeover:
            logger.critical('[脚本] 请求人工接管')
            exit(1)
        except Exception as e:
            logger.exception(e)
            exit(1)

    @cached_property
    def checker(self):
        """
        占位函数，在alas中是检查服务器是否正常的
        :return:
        """
        return None

    def save_error_log(self):
        """
        保存错误现场到 ./log/error/<script_name>_<timestamp_ms>。

        保存内容包括:
        - 最近一段截图, 文件名为时间戳 PNG。
        - 当前脚本日志的截取内容, 文件名为 log.txt。

        说明:
        - 新错误目录名会带上脚本名, 便于前端区分不同脚本产生的错误。
        - 目录名和脚本名都会经过统一净化, 避免路径注入。
        """
        from module.base.utils import save_image
        from module.handler.sensitive_info import (handle_sensitive_image,
                                                   handle_sensitive_logs)
        if self.config.script.error.save_error:
            if not os.path.exists('./log/error'):
                os.mkdir('./log/error')
            # 用统一规则生成错误目录名, 目录格式为 <script_name>_<timestamp_ms>。
            folder_name = build_error_log_dir_name(self.config_name, int(time.time() * 1000))
            folder = f'./log/error/{folder_name}'
            logger.warning(f'[脚本] 正在保存错误现场: {folder}')
            os.mkdir(folder)
            for data in self.device.screenshot_deque:
                image_time = datetime.strftime(data['time'], '%Y-%m-%d_%H-%M-%S-%f')
                image = handle_sensitive_image(data['image'])
                save_image(image, f'{folder}/{image_time}.png')
            with open(logger.log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                start = 0
                for index, line in enumerate(lines):
                    line = line.strip(' \r\t\n')
                    if re.match('^═{15,}$', line):
                        start = index
                lines = lines[start - 2:]
                lines = handle_sensitive_logs(lines)
            with open(f'{folder}/log.txt', 'w', encoding='utf-8') as f:
                f.writelines(lines)

    def init_server(self, port: int) -> int:
        """
        初始化zerorpc服务，返回端口号
        :return:
        """
        self.server = zerorpc.Server(self)
        try:
            self.server.bind(f'tcp://127.0.0.1:{port}')
            return port
        except zmq.error.ZMQError:
            logger.error(f"[脚本] OCR 服务无法绑定端口 {port}")
            return None

    def run_server(self) -> None:
        """
        启动zerorpc服务
        :return:
        """
        self.server.run()

    def gui_args(self, task: str) -> str:
        """
        获取给gui显示的参数
        :return:
        """
        return self.config.gui_args(task=task)

    def gui_menu(self) -> str:
        """
        获取给gui显示的菜单
        :return:
        """
        return self.config.gui_menu

    def gui_task(self, task: str) -> str:
        """
        获取给gui显示的任务 的参数的具体值
        :return:
        """
        return self.config.model.gui_task(task=task)

    def gui_set_task(self, task: str, group: str, argument: str, value) -> bool:
        """
        设置给gui显示的任务 的参数的具体值
        :return:
        """
        # 验证参数
        task = convert_to_underscore(task)
        group = convert_to_underscore(group)
        argument = convert_to_underscore(argument)
        # pandtic验证
        if isinstance(value, str):
            if len(value) == 8:
                try:
                    value = datetime.strptime(value, '%H:%M:%S').time()
                except ValueError:
                    pass


        path = f'{task}.{group}.{argument}'
        task_object = getattr(self.config.model, task, None)
        group_object = getattr(task_object, group, None)
        argument_object = getattr(group_object, argument, None)

        if argument_object is None:
            logger.error(f'[脚本] 设置参数 {task}.{group}.{argument}.{value} 失败')
            return False

        try:
            setattr(group_object, argument, value)
            argument_object = getattr(group_object, argument, None)
            logger.info(f'[脚本] 设置参数 {task}.{group}.{argument}.{argument_object}')
            self.config.save()  # 我是没有想到什么方法可以使得属性改变自动保存的
            return True
        except ValidationError as e:
            logger.error(e)
            return False

    @zerorpc.stream
    def gui_mirror_image(self):
        """
        获取给gui显示的镜像
        :return: cv2的对象将 numpy 数组转换为字节串。接下来MsgPack 进行序列化发送方将图像数据转换为字节串
        """
        # return msgpack.packb(cv2.imencode('.jpg', self.device.screenshot())[1].tobytes())
        img = cv2.cvtColor(self.device.screenshot(), cv2.COLOR_RGB2BGR)
        self.device.stuck_record_clear()
        ret, buffer = cv2.imencode('.jpg', img)
        yield buffer.tobytes()

    def _gui_update_tasks(self) -> None:
        """
        获取更新任务后 pending waiting 的任务 和 当前的任务的数据。打包给gui显示
        :return:
        """
        data = {}
        pending = []
        waiting = []
        task = {}
        if self.config.task is not None and self.config.task.next_run < datetime.now():
            task["name"] = self.config.task.command
            task["next_run"] = str(self.config.task.next_run)
        data["task"] = task

        for p in self.config.pending_task[1:]:
            item = {"name": p.command, "next_run": str(p.next_run)}
            pending.append(item)

        for w in self.config.waiting_task:
            item = {"name": w.command, "next_run": str(w.next_run)}
            waiting.append(item)


        data["pending"] = pending
        data["waiting"] = waiting

        if self.gui_update_task is not None:
            self.gui_update_task(data)

    def _gui_set_status(self, status: str) -> None:
        """
        设置给gui显示的状态
        :param status: 可以在gui中显示的状态 有 "Init", "Empty"(不显示), "Run"(运行中), "Error", "Free"(空闲)
        :return:
        """
        data = {"status": status}
        if self.gui_update_task is not None:
            self.gui_update_task(data)

    def gui_task_list(self) -> str:
        """
        获取给gui显示的任务列表
        :return:
        """
        result = {}
        for key, value in self.config.model.dict().items():
            if isinstance(value, str):
                continue
            if key == "restart":
                continue
            if "scheduler" not in value:
                continue

            scheduler = value["scheduler"]
            item = {"enable": scheduler["enable"],
                    "next_run": str(scheduler["next_run"])}
            key = self.config.model.type(key)
            result[key] = item
        return json.dumps(result)

    def wait_until(self, future):
        """
        Wait until a specific time.

        Args:
            future (datetime):

        Returns:
            bool: True if wait finished, False if config changed.
        """
        future = future + timedelta(seconds=1)
        self.config.start_watching()
        while 1:
            if datetime.now() > future:
                return True
            # if self.stop_event is not None:
            #     if self.stop_event.is_set():
            #         logger.info("Update event detected")
            #         logger.info(f"[{self.config_name}] exited. Reason: Update")
            #         exit(0)

            time.sleep(5)

            if self.config.should_reload():
                return False

    def _hoard_next_task(self, task, now: datetime):
        """在空闲时延迟首个到期任务，窗口内到达的任务一并等待。"""
        duration = self.config.script.optimization.task_hoarding_duration
        if duration <= 0 or not self.config.pending_task:
            self.task_hoarding_until = None
            self.task_hoarding_released = False
            return task

        if (self.config.model.running_task or self.task_hoarding_released
                or (self.is_first_task and task.command == 'Restart')
                or (task.next_run > now and self.task_hoarding_until is None)):
            return task

        if self.task_hoarding_until is None:
            self.task_hoarding_until = now + timedelta(minutes=duration)
            logger.info(
                f"Task hoarding started for {duration:g} minutes, "
                f"release at {self.task_hoarding_until.strftime('%Y-%m-%d %H:%M:%S')}"
            )

        if now < self.task_hoarding_until:
            task = copy.deepcopy(task)
            task.next_run = max(self.task_hoarding_until, task.next_run)
            logger.info(
                f"Task hoarding active, defer pending tasks until "
                f"{self.task_hoarding_until.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            return task

        self.task_hoarding_until = None
        self.task_hoarding_released = True
        logger.info("Task hoarding window ended, resume scheduled task execution")
        return task

    @staticmethod
    def _parse_continuous_task_interval(value: str) -> tuple[int, int]:
        """解析连续任务休息间隔，格式为“最小分钟,最大分钟”。"""
        matched = re.fullmatch(r'\s*(\d+)\s*[,，]\s*(\d+)\s*', str(value))
        if matched is None:
            raise ValueError(f'无效的连续任务休息间隔: {value!r}')
        lower, upper = (int(item) for item in matched.groups())
        if lower <= 0 or upper <= 0 or lower > upper:
            raise ValueError(f'无效的连续任务休息间隔: {value!r}')
        return lower, upper

    @staticmethod
    def _sample_continuous_task_rest_seconds() -> tuple[int, str]:
        """休息时长：90% 落在2-8分钟的对称三角分布，其余10% 在8-20分钟内逐渐降低概率。"""
        if random.random() < 0.9:
            minutes = random.triangular(2, 8, 5)
            branch = '短休息'
        else:
            minutes = random.triangular(8, 20, 8)
            branch = '长尾'
        return max(120, min(1200, round(minutes * 60))), branch

    def _reset_continuous_task_rest(self, *, log_idle: bool = False) -> None:
        if log_idle and self._continuous_task_started_at is not None:
            logger.info('[脚本] 调度器进入任务等待状态，重置连续任务计时')
        self._continuous_task_started_at = None
        self._continuous_task_limit_seconds = None
        self._continuous_task_interval_range = None

    def _handle_continuous_task_rest(self) -> bool:
        """在新任务开始前处理连续运行休息，已休息时返回 True 要求重新调度。"""
        device_config = self.config.script.device
        if not device_config.continuous_task_rest_enable:
            self._reset_continuous_task_rest()
            return False

        try:
            interval_range = self._parse_continuous_task_interval(
                device_config.continuous_task_rest_interval
            )
        except ValueError as exc:
            logger.warning(f'[脚本] {exc}，回退使用 60,120 分钟')
            interval_range = (60, 120)

        now = time.monotonic()
        if (
            self._continuous_task_started_at is None
            or self._continuous_task_interval_range != interval_range
        ):
            limit_minutes = random.randint(*interval_range)
            self._continuous_task_started_at = now
            self._continuous_task_limit_seconds = limit_minutes * 60
            self._continuous_task_interval_range = interval_range
            logger.info(
                '[脚本] 连续任务计时启动: '
                f'上限={limit_minutes}分钟, 范围={interval_range[0]}-{interval_range[1]}分钟'
            )
            return False

        elapsed = now - self._continuous_task_started_at
        if elapsed < self._continuous_task_limit_seconds:
            return False

        rest_seconds, branch = self._sample_continuous_task_rest_seconds()
        logger.info(
            '[脚本] 达到连续任务时长上限: '
            f'已连续={elapsed / 60:.1f}分钟, '
            f'休息={rest_seconds / 60:.1f}分钟, 分布={branch}'
        )
        time.sleep(rest_seconds)
        self._reset_continuous_task_rest()
        logger.info('[脚本] 连续任务休息结束，重新调度任务')
        return True

    def get_next_task(self) -> str:
        """
        获取下一个任务的名字, 大驼峰。
        :return:
        """
        while True:
            task = self.config.get_next()
            now = datetime.now()
            antiban_wake = self.anti_ban_guard.wake_time(now, self.config.script.anti_ban)
            if antiban_wake is not None:
                task.next_run = max(task.next_run, antiban_wake)
            task = self._hoard_next_task(task, now)
            self.config.task = task
            if self.state_queue:
                self.state_queue.put({"schedule": self.config.get_schedule_data()})
            # 任务时间到了返回任务名称
            if task.next_run <= now:
                # 连续执行达到上限时先休息，休息后重新调度
                if self._handle_continuous_task_rest():
                    continue
                return task.command
            self._reset_continuous_task_rest(log_idle=True)
            # 根据策略执行等待逻辑
            wait_until = task.next_run
            if self.task_hoarding_until and self.config.waiting_task:
                wait_until = min(wait_until, self.config.waiting_task[0].next_run)
            decision = self.runtime.handle_wait_during_idle(wait_until)
            if decision == ScriptRuntimeDecision.RESCHEDULE:
                logger.info('[脚本] 空闲等待请求刷新调度器，重新加载配置并重新调度')
                del_cached_property(self, "config")
            elif decision == ScriptRuntimeDecision.FAILED:
                logger.warning('[脚本] 空闲等待准备失败，重新加载配置并重试调度')
                del_cached_property(self, "config")

    def exception_handler(self, e: Exception, command: str) -> None:
        # 处理御魂溢出
        from tasks.Utils.post_diagnotor import PostDiagnotor, AnalyzeType
        image = getattr(self.device, 'image', None)
        # image为None则不做处理
        if image is None:
            return
        analyse_type = PostDiagnotor().handle(e=e, command=command, image=image)
        if analyse_type == AnalyzeType.SoulOverflow:
            self.config.task_call('SoulsTidy')
            time.sleep(1)

    def _reset_task_runtime_outcome(self) -> None:
        self.last_task_runtime_outcome = None
        if 'config' in self.__dict__:
            self.config.task_runtime_outcome = None

    def _set_task_runtime_outcome(self, task: str, status: str, wait_until: datetime | None = None) -> None:
        outcome = {
            'task': task,
            'status': status,
        }
        if wait_until is not None:
            outcome['wait_until'] = wait_until
        self.last_task_runtime_outcome = outcome
        if 'config' in self.__dict__:
            self.config.task_runtime_outcome = outcome

    def _capture_task_runtime_outcome(self, command: str) -> None:
        outcome = getattr(self.config, 'task_runtime_outcome', None)
        self.last_task_runtime_outcome = outcome if isinstance(outcome, dict) else None
        if self.last_task_runtime_outcome is None:
            return
        status = self.last_task_runtime_outcome.get('status')
        if status == 'server_update_delayed':
            wait_until = self.last_task_runtime_outcome.get('wait_until')
            logger.info(f'[脚本] {command} 运行结果: server_update_delayed (wait_until={wait_until})')
            if isinstance(wait_until, datetime):
                self.runtime.server_update_wait_until = wait_until
                self.runtime.server_update_wait_log_until = None
            return
        if command != 'Restart':
            return
        if status == 'recovered':
            logger.info('[脚本] Restart 运行结果: recovered')
            return
        logger.info(f'[脚本] Restart 运行结果: {status}')

    def _delay_tasks_for_server_update(self, task: str, reason: str) -> bool:
        if not is_server_update_window():
            return False

        delay_target = delay_pending_tasks_for_server_update(self.config, reason=reason)
        self._set_task_runtime_outcome(task=task, status='server_update_delayed', wait_until=delay_target)
        return True

    def _reset_page_unknown_backoff(self) -> None:
        """任务成功后复位页面识别退避计数。"""
        if self._page_unknown_fail_times or self._page_unknown_backoff_round:
            self._page_unknown_fail_times = []
            self._page_unknown_backoff_round = 0
            logger.info('[脚本] 页面识别已恢复正常，重置退避计数')

    def _register_page_unknown_failure(self) -> datetime | None:
        """
        记录一次页面识别失败。
        统计窗口内失败达到阈值时返回本次退避的等待目标时间，否则返回 None。
        """
        now = datetime.now()
        self._page_unknown_fail_times = [
            t for t in self._page_unknown_fail_times if now - t <= PAGE_UNKNOWN_FAIL_WINDOW
        ]
        self._page_unknown_fail_times.append(now)
        if len(self._page_unknown_fail_times) < PAGE_UNKNOWN_FAIL_LIMIT:
            return None
        self._page_unknown_backoff_round += 1
        duration_seconds = min(
            PAGE_UNKNOWN_BACKOFF_BASE.total_seconds() * (2 ** (self._page_unknown_backoff_round - 1)),
            PAGE_UNKNOWN_BACKOFF_CAP.total_seconds(),
        )
        self._page_unknown_fail_times = []
        return now + timedelta(seconds=duration_seconds)

    def _delay_all_pending_tasks(self, target: datetime) -> None:
        """把所有到期与未到期的任务（含 Restart）推迟到指定时间。"""
        self.config.update_scheduler()
        delayed = set()
        candidates = list(getattr(self.config, 'pending_task', []))
        candidates.extend(getattr(self.config, 'waiting_task', []))
        for task in candidates:
            command = task.command
            if command in delayed or command == 'Restart':
                continue
            if not isinstance(task.next_run, datetime) or task.next_run >= target:
                continue
            self.config.task_delay(task=command, server=False, target=target)
            delayed.add(command)
        self.config.task_delay(task='Restart', server=False, target=target)

    def _enter_page_unknown_backoff(self, target: datetime) -> None:
        """页面识别连续失败：关闭游戏安静等待，避免无限重启循环。"""
        logger.warning(
            f'[脚本] 页面识别连续失败，第 {self._page_unknown_backoff_round} 轮退避，'
            f'暂停运行至 {target.strftime("%Y-%m-%d %H:%M:%S")}'
        )
        self.runtime.server_update_wait_reason = '页面识别退避'
        self.runtime.server_update_wait_until = target
        self.runtime.server_update_wait_log_until = None
        self.config.notifier.push(
            title='页面识别连续失败',
            content=f'<{self.config_name}> 已暂停运行至 {target.strftime("%H:%M")}，期满自动恢复',
        )
        self._delay_all_pending_tasks(target)

    def run(self, command: str) -> bool:
        """
        :param command:  大写驼峰命名的任务名字
        :return:
        """
        if command == 'start' or command == 'goto_main':
            logger.error(f'[脚本] 无效命令 `{command}`')

        self._reset_task_runtime_outcome()
        try:
            self.device.screenshot()
            module_name = 'script_task'
            module_path = str(Path.cwd() / 'tasks' / command / (module_name + '.py'))
            logger.info(f'[脚本] 模块路径: {module_path}, 模块名: {module_name}')
            task_module = load_module(module_name, module_path)
            task_module.ScriptTask(config=self.config, device=self.device).run()
        except Exception as e:
            return self._handle_task_exception(e, command)
        return False

    def loop(self):
        """
        Main loop of scheduler.
        :return:
        """
        with _log_switch_lock:
            logger.set_file_logger(self.config_name, do_cleanup=True)
        start_day = date.today()
        logger.info(f'[脚本] 启动调度循环: {self.config_name}')
        if self.resource_precache_enable:
            logger.info('[脚本] 资源预缓存已启用，正在预热 OCR 模型')
            try:
                get_ocr_client().warmup()
            except Exception as exc:
                logger.exception(exc)
                raise ScriptError('OCR 模型资源预缓存失败') from exc
            logger.info('[脚本] 资源预缓存完成，调度任务可以开始')
        self.config.model.running_task = ''
        self.anti_ban_guard.reset()

        # Update GUI 防呆, 读取设置并立刻显示后台模拟器到前台
        if not self.config.script.device.run_background_only and IS_WINDOWS:
            from module.device.platform2.platform_windows import minimize_by_name, show_window_by_name
            target_window_name = self.config.script.device.handle  # 在这里输入你的具体窗口名称
            if self.config.script.device.emulator_window_minimize:
                minimize_by_name(target_window_name)
                logger.info(f'重新显示: {target_window_name}')
            else:
                show_window_by_name(target_window_name)
                
        while 1:
            if date.today() > start_day:
                with _log_switch_lock:
                    logger.set_file_logger(self.config_name, do_cleanup=True)
                start_day = date.today()

            task = ""
            try:
                # Get task
                self.config.reload()
                self.config.update_scheduler()
                if not self.config.pending_task and not self.config.waiting_task:
                    logger.info('[脚本] 没有已启用的任务，调度器正常结束')
                    break
                task = self.get_next_task()
                # Skip first restart
                if self.is_first_task and task == 'Restart':
                    logger.info('[脚本] 调度启动时跳过任务 `Restart`')
                    self.config.task_delay(task='Restart', success=True, server=True)
                    del_cached_property(self, 'config')
                    continue
                decision = self.runtime.prepare_task_execution(task)
            except Exception as e:
                self._handle_task_exception(e, task)
                # 本轮 prepare 失败,重新调度
                del_cached_property(self, 'config')
                continue

            if decision == ScriptRuntimeDecision.RESCHEDULE:
                logger.info(f'[脚本] `{task}` 运行准备请求重新调度，重新加载配置并重试调度')
                del_cached_property(self, 'config')
                continue
            if decision == ScriptRuntimeDecision.FAILED:
                logger.warning(f'[脚本] `{task}` 运行准备失败，重新加载配置并重试调度')
                del_cached_property(self, 'config')
                continue

            # Run
            logger.info(f'[脚本] 调度: 开始任务 `{task}`')
            self.device.stuck_record_clear()
            self.device.click_record_clear()
            logger.hr(task, level=0)
            self.config.model.running_task = task
            _task_start = datetime.now()
            RuleScatter.begin_task(task)
            try:
                success = self.run(inflection.camelize(task))
            finally:
                RuleScatter.end_task(task)
            self.config.model.running_task = ''
            logger.info(f'[脚本] 调度: 任务 `{task}` 执行结束')
            if getattr(self.config, 'request_scheduler_stop', False):
                logger.info('[脚本] 收到调度停止请求，结束调度循环')
                break
            self.is_first_task = False
            self.anti_ban_guard.record_active((datetime.now() - _task_start).total_seconds())

            # Check failures
            # failed = deep_get(self.failure_record, keys=task, default=0)
            failed = self.failure_record[task] if task in self.failure_record else 0
            failed = 0 if success else failed + 1
            # deep_set(self.failure_record, keys=task, value=failed)
            self.failure_record[task] = failed
            if failed >= 3:
                logger.critical(f"[脚本] 任务 `{task}` 失败 3 次或以上")
                logger.critical("[脚本] 可能原因一: 未正确使用该任务，"
                                "请阅读选项的帮助文本")
                logger.critical("[脚本] 可能原因二: 该任务本身可能存在问题，"
                                "请联系开发者或自行尝试修复")
                logger.critical('[脚本] 请求人工接管')
                # 添加失败三次的推送通知
                self.config.notifier.push(
                    title=f'{I18n.trans_zh_cn(task)}{task}',
                    content=f"<{self.config_name}> 任务连续失败三次，请上线查看"
                )
                # 关闭模拟器
                if self.config.script.error.error_repeated:
                    self.device.emulator_stop()
                exit(1)

            if success:
                self._reset_page_unknown_backoff()
                del_cached_property(self, 'config')
                continue
            elif self.config.script.error.handle_error:
                # self.config.task_delay(success=False)
                del_cached_property(self, 'config')
                # self.checker.check_now()
                continue
            else:
                break

    def _handle_task_exception(self, e: Exception, command: str) -> bool:
        """
        统一处理任务执行 / 准备阶段抛出的异常。
        Returns:
            True  -> 视为正常结束或已自动恢复 (例如已 task_call('Restart')),
                     调度器继续推进
            False -> 视为失败,脚本继续运行
        对致命异常 (ScriptError / RequestHumanTakeover / 未识别 Exception)
        在内部直接 exit(1)。
        """
        if isinstance(e, TaskEnd):
            self._capture_task_runtime_outcome(command)
            return True

        if isinstance(e, GameNotRunningError):
            logger.warning(e)
            self.exception_handler(e=e, command=command)
            self.config.task_call('Restart')
            return True

        if isinstance(e, (GameStuckError, GameTooManyClickError)):
            logger.error(e)
            self.save_error_log()
            self.exception_handler(e=e, command=command)
            logger.warning(f'[脚本] 游戏卡住，{self.device.package} 将在 10 秒后重启')
            logger.warning('[脚本] 如果正在手动游玩，请先停止 Oas')
            self.config.notifier.push(title=f'{I18n.trans_zh_cn(command)}{command}',
                                      content=f"<{self.config_name}> GameStuckError or GameTooManyClickError")
            self.config.task_call('Restart')
            self.device.sleep(10)
            return False

        if isinstance(e, GameBugError):
            logger.warning(e)
            self.save_error_log()
            self.exception_handler(e=e, command=command)
            logger.warning('[脚本] 游戏客户端发生错误，Oas 无法处理')
            logger.warning(f'[脚本] 正在重启 {self.device.package} 以修复')
            self.config.task_call('Restart')
            self.device.sleep(10)
            return False

        if isinstance(e, GamePageUnknownError):
            logger.info('[脚本] 游戏服务器可能正在维护或网络已断开，正在检查服务器状态')
            if command == 'GotoMain' and self._delay_tasks_for_server_update(
                    task=command,
                    reason='维护窗口内 GotoMain 失败',
            ):
                logger.info('[脚本] 服务器更新窗口内 GotoMain 失败，已延迟待执行任务并重新调度')
                return False
            backoff_target = self._register_page_unknown_failure()
            if backoff_target is not None:
                self._enter_page_unknown_backoff(backoff_target)
                return False
            logger.critical('[脚本] 未知游戏页面')
            self.save_error_log()
            self.exception_handler(e=e, command=command)
            self.config.notifier.push(
                title=f'{I18n.trans_zh_cn(command)}{command}',
                content=f"<{self.config_name}> GamePageUnknownError",
            )
            self.config.task_call('Restart')
            self.device.sleep(10)
            return False

        if isinstance(e, ScriptError):
            logger.critical(e)
            self.exception_handler(e=e, command=command)
            logger.critical('[脚本] 这可能是开发者的失误，但有时只是偶发问题')
            self.config.notifier.push(
                title=f'{I18n.trans_zh_cn(command)}{command}',
                content=f"<{self.config_name}> ScriptError",
            )
            exit(1)

        if isinstance(e, RequestHumanTakeover):
            logger.critical(e)
            self.exception_handler(e=e, command=command)
            logger.critical('[脚本] 请求人工接管')
            self.config.notifier.push(
                title=f'{I18n.trans_zh_cn(command)}{command}',
                content=f"<{self.config_name}> RequestHumanTakeover",
            )
            exit(1)

        # generic
        logger.exception(e)
        self.exception_handler(e=e, command=command)
        self.save_error_log()
        self.config.notifier.push(
            title=f'{I18n.trans_zh_cn(command)}{command}',
            content=f"<{self.config_name}> Exception occured",
        )
        exit(1)
        return False

    def start_loop(self) -> None:
        """
        创建一个线程，运行loop
        :return:
        """
        if self.loop_thread is None:
            self.loop_thread = Thread(target=self.loop, name='Script_loop')
            self.loop_thread.start()


if __name__ == "__main__":
    ensure_image_server_ready()
    ensure_ocr_server_ready()
    script = Script("oas1")
    script.loop()
