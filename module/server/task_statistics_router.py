# This Python file uses the following encoding: utf-8
"""
任务执行统计分析：解析脚本日志中的任务运行段，聚合执行次数 / 成功率 / 时长 / 战斗次数。

路由:
  GET /task_statistics_page                    统计分析页面
  GET /task_statistics/api/scripts             实例（配置）列表
  GET /task_statistics/api/summary             聚合数据（统计卡片、趋势、分布、记录表）

数据来源: log/YYYY-MM-DD_<脚本名>.txt
  任务开始: [脚本] 调度: 开始任务 `TaskName`
  任务结束: [脚本] 调度: 任务 `TaskName` 执行结束
  战斗边界: ──── 通用战斗开始 ────
成败判定: 运行段内出现 ERROR/CRITICAL 或未走到「执行结束」记为失败；
错误类型取段内最后一条 ERROR/CRITICAL 文案（截断展示）。
任务跨午夜时运行段会跨日志文件续接，不拆成两段。
"""
from __future__ import annotations

import re
from collections import OrderedDict
from datetime import date as date_cls, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from module.server.analysis_router import _resolve_task_filter, list_scripts, task_display_name
from module.server.api_logger import ApiLoggingRoute

PROJECT_ROOT = Path.cwd().resolve()
LOG_ROOT = (PROJECT_ROOT / "log").resolve()
WEB_DIR = Path(__file__).resolve().parent / "web" / "task_statistics"

_LOG_FILE_RE = re.compile(r"^(?P<day>\d{4}-\d{2}-\d{2})_(?P<script>.+)\.txt$")
_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\s+\|"
    r"\s*(?P<src>\S+)\s*\|\s*(?P<level>[A-Z]+)\s*\|\s?(?P<msg>.*)$"
)
_TASK_START_RE = re.compile(r"\[脚本\] 调度: 开始任务 `(?P<task>[A-Za-z0-9_]+)`")
_TASK_END_RE = re.compile(r"\[脚本\] 调度: 任务 `(?P<task>[A-Za-z0-9_]+)` 执行结束")
_TITLE_LINE_RE = re.compile(r"^─{10,}\s*(?P<title>.*?)\s*─{10,}\s*$")
# 战斗边界标题需兼容中文化前后的日志格式
_BATTLE_TITLES = {"GENERAL BATTLE START", "通用战斗开始"}
_ERROR_LEVELS = {"ERROR", "CRITICAL"}
_ERROR_MSG_MAX = 60
_RUN_CACHE_LIMIT = 96
_RUNNING_FRESH_SECONDS = 600

task_stats_app = APIRouter(
    tags=["task_statistics"],
    route_class=ApiLoggingRoute,
)

# 文件解析缓存：键为日志文件路径，值为 (签名, 已闭合运行段, 未闭合尾段, 文件最后时间戳)
_run_cache: OrderedDict[Path, tuple[tuple[int, int], list[dict[str, Any]], dict[str, Any] | None, datetime | None]] = OrderedDict()


@task_stats_app.get("/task_statistics_page")
async def task_statistics_page():
    index_file = WEB_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail={"code": "page_not_found", "message": "统计分析页面不存在"})
    return FileResponse(index_file)


@task_stats_app.get("/task_statistics/api/scripts")
async def task_statistics_scripts():
    names = list_scripts()
    # 只保留真实配置对应的实例，过滤 test/script 之类临时日志
    config_dir = PROJECT_ROOT / "config"
    real_names = [name for name in names if (config_dir / f"{name}.json").is_file()]
    return {"scripts": real_names or names}


@task_stats_app.get("/task_statistics/api/summary")
async def task_statistics_summary(
    script: str = Query(..., description="实例（脚本）名"),
    start: str = Query(default="", description="开始时间 YYYY-MM-DD HH:MM:SS"),
    end: str = Query(default="", description="结束时间 YYYY-MM-DD HH:MM:SS"),
    task: str = Query(default="", description="任务筛选，支持中文或 CamelCase 名"),
):
    today = date_cls.today()
    if not start:
        start = f"{today.isoformat()} 00:00:00"
    if not end:
        end = f"{today.isoformat()} 23:59:59"
    start_dt, end_dt = _parse_window(start, end)
    return _build_summary(script, start_dt, end_dt, task)


def _parse_window(start_text: str, end_text: str) -> tuple[datetime, datetime]:
    # 兼容浏览器 datetime-local 省略秒、以及仅传日期的写法
    fmts = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d")

    def parse_one(text: str) -> datetime:
        for fmt in fmts:
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        raise HTTPException(status_code=422, detail="时间格式应为 YYYY-MM-DD HH:MM:SS")

    start_dt = parse_one(start_text)
    end_dt = parse_one(end_text)
    if end_dt < start_dt:
        start_dt, end_dt = end_dt, start_dt
    return start_dt, end_dt


def _parse_ts(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S.%f")


def _script_files_between(script_name: str, start_dt: datetime, end_dt: datetime) -> list[Path]:
    if not LOG_ROOT.exists():
        return []
    files: list[Path] = []
    for path in LOG_ROOT.iterdir():
        matched = _LOG_FILE_RE.match(path.name)
        if not matched or matched.group("script") != script_name:
            continue
        try:
            day = datetime.strptime(matched.group("day"), "%Y-%m-%d")
        except ValueError:
            continue
        # 任务可能跨天，多取前后各一天的日志兜底
        if day.date() < start_dt.date() - timedelta(days=1):
            continue
        if day.date() > end_dt.date() + timedelta(days=1):
            continue
        files.append(path)
    files.sort()
    return files


def _load_runs(script_name: str, start_dt: datetime, end_dt: datetime) -> tuple[list[dict[str, Any]], datetime | None]:
    """扫描时间范围覆盖的日志文件，返回按开始时间正序的运行段列表与数据末尾时间戳。"""
    runs: list[dict[str, Any]] = []
    data_last_ts: datetime | None = None
    carry: dict[str, Any] | None = None  # 上一文件遗留的未闭合运行段（跨午夜续接）

    for path in _script_files_between(script_name, start_dt, end_dt):
        stat = path.stat()
        signature = (int(stat.st_size), int(stat.st_mtime_ns))
        cached = _run_cache.get(path)
        if cached is not None and cached[0] == signature and carry is None:
            _run_cache.move_to_end(path)
            file_runs, carry, file_last_ts = cached[1], cached[2], cached[3]
        else:
            file_runs, carry, file_last_ts = _parse_file(path, initial_current=carry)
            if carry is None:
                _run_cache[path] = (signature, file_runs, carry, file_last_ts)
                while len(_run_cache) > _RUN_CACHE_LIMIT:
                    _run_cache.popitem(last=False)

        if file_last_ts is not None and (data_last_ts is None or file_last_ts > data_last_ts):
            data_last_ts = file_last_ts
        runs.extend(file_runs)

    # 全部文件结束后仍未闭合的段（如今天正在运行的任务）按数据末尾收口
    if carry is not None:
        carry["end"] = data_last_ts
        carry["explicit_end"] = False
        runs.append(carry)

    runs.sort(key=lambda r: r["start"])
    return runs, data_last_ts


def _parse_file(
    path: Path,
    initial_current: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, datetime | None]:
    """解析单个日志文件。

    返回 (已闭合运行段, 未闭合尾段, 文件最后时间戳)。
    initial_current 为上一文件续接来的未闭合运行段，会优先在本文件中寻找其结束标记。
    """
    runs: list[dict[str, Any]] = []
    current = initial_current
    file_last_ts: datetime | None = None
    pending_battle = False

    def close_current(end_ts: datetime | None, explicit: bool) -> None:
        nonlocal current
        if current is None:
            return
        current["end"] = end_ts
        current["explicit_end"] = explicit
        runs.append(current)
        current = None

    with path.open("r", encoding="utf-8", errors="ignore") as file:
        for raw in file:
            line = raw.rstrip("\r\n")

            # 无时间戳的边界行：判定是否战斗开始
            if not line[:4].isdigit():
                matched = _TITLE_LINE_RE.match(line.strip())
                if matched and matched.group("title").strip().upper() in _BATTLE_TITLES:
                    pending_battle = True
                continue

            matched = _LINE_RE.match(line)
            if not matched:
                continue
            ts = _parse_ts(matched.group("ts"))
            file_last_ts = ts
            level = matched.group("level")
            msg = matched.group("msg")

            start_match = _TASK_START_RE.search(msg)
            if start_match:
                close_current(ts, explicit=False)
                current = {
                    "task": start_match.group("task"),
                    "start": ts,
                    "end": None,
                    "explicit_end": False,
                    "battle_starts": [],
                    "error_msg": None,
                }
                pending_battle = False
                continue

            if current is not None:
                end_match = _TASK_END_RE.search(msg)
                if end_match and end_match.group("task") == current["task"]:
                    close_current(ts, explicit=True)
                    continue
                if pending_battle:
                    current["battle_starts"].append(ts)
                    pending_battle = False
                if level in _ERROR_LEVELS:
                    text = msg.strip()
                    if text:
                        current["error_msg"] = text[:_ERROR_MSG_MAX]

    close_current(file_last_ts, explicit=False)
    return runs, current, file_last_ts


def _finalize_run(run: dict[str, Any], data_last_ts: datetime | None) -> None:
    """补齐战斗时长与结果状态。"""
    end = run["end"]
    battle_starts = run["battle_starts"]
    battle_total = 0.0
    for index, battle_start in enumerate(battle_starts):
        battle_end = battle_starts[index + 1] if index + 1 < len(battle_starts) else end
        if battle_end is not None and battle_end > battle_start:
            battle_total += (battle_end - battle_start).total_seconds()
    run["battle_count"] = len(battle_starts)
    run["battle_seconds"] = round(battle_total, 1)

    if run["explicit_end"] and end is not None and not run["error_msg"]:
        run["status"] = "success"
        return

    # 未走到「执行结束」：持续到数据末尾且日志仍在更新 → 进行中，否则视为失败
    reached_data_end = end is not None and data_last_ts is not None and end >= data_last_ts
    fresh = (
        data_last_ts is not None
        and (datetime.now() - data_last_ts).total_seconds() < _RUNNING_FRESH_SECONDS
    )
    if reached_data_end and fresh:
        run["status"] = "running"
        return

    run["status"] = "failed"
    if not run["error_msg"]:
        run["error_msg"] = "任务未正常结束"


def _bucket_key(ts: datetime, span_hours: float) -> str:
    if span_hours <= 48:
        return f"{ts.hour}:00"
    return ts.strftime("%m-%d")


def _build_summary(script_name: str, start_dt: datetime, end_dt: datetime, task_filter: str) -> dict[str, Any]:
    runs, data_last_ts = _load_runs(script_name, start_dt, end_dt)
    for run in runs:
        _finalize_run(run, data_last_ts)

    # ±1 天兜底文件会带来窗口外的运行段，这里按所选时间范围过滤
    runs = [
        r for r in runs
        if r["start"] <= end_dt and (r["end"] or r["start"]) >= start_dt
    ]

    if task_filter:
        camel = _resolve_task_filter(task_filter)
        runs = [r for r in runs if r["task"] == camel or task_display_name(r["task"]) == task_filter]

    closed = [r for r in runs if r["status"] != "running"]
    success = sum(1 for r in closed if r["status"] == "success")
    failed = len(closed) - success
    running = len(runs) - len(closed)
    total_duration = sum((r["end"] - r["start"]).total_seconds() for r in closed if r["end"])
    total_battles = sum(r["battle_count"] for r in runs)

    span_hours = (end_dt - start_dt).total_seconds() / 3600
    trend: OrderedDict[str, dict[str, Any]] = OrderedDict()
    if span_hours <= 48:
        bucket = start_dt.replace(minute=0, second=0, microsecond=0)
        while bucket <= end_dt:
            trend[_bucket_key(bucket, span_hours)] = {"count": 0, "duration": 0.0, "avg_count": 0}
            bucket += timedelta(hours=1)
    for run in runs:
        key = _bucket_key(run["start"], span_hours)
        item = trend.setdefault(key, {"count": 0, "duration": 0.0, "avg_count": 0})
        item["count"] += 1
        if run["status"] != "running" and run["end"]:
            item["duration"] += (run["end"] - run["start"]).total_seconds()
            item["avg_count"] += 1
    trend_payload = [
        {
            "bucket": key,
            "run_count": item["count"],
            "avg_duration_minutes": round(item["duration"] / item["avg_count"] / 60, 2) if item["avg_count"] else 0,
        }
        for key, item in trend.items()
    ]

    distribution: OrderedDict[str, dict[str, Any]] = OrderedDict()
    ranking: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for run in runs:
        name = task_display_name(run["task"])
        dist = distribution.setdefault(name, {"task": name, "run_count": 0})
        dist["run_count"] += 1
        if run["status"] != "running" and run["end"]:
            rank = ranking.setdefault(name, {"task": name, "total_minutes": 0.0})
            rank["total_minutes"] += (run["end"] - run["start"]).total_seconds() / 60
    distribution_payload = sorted(
        distribution.values(),
        key=lambda item: item["run_count"],
        reverse=True,
    )
    ranking_payload = sorted(
        ({"task": item["task"], "total_minutes": round(item["total_minutes"], 2)} for item in ranking.values()),
        key=lambda item: item["total_minutes"],
        reverse=True,
    )

    records = [
        {
            "task": task_display_name(run["task"]),
            "start_time": run["start"].strftime("%Y-%m-%d %H:%M:%S"),
            "end_time": run["end"].strftime("%Y-%m-%d %H:%M:%S") if run["end"] else "",
            "duration_seconds": round((run["end"] - run["start"]).total_seconds(), 1) if run["end"] else 0,
            "avg_battle_seconds": round(run["battle_seconds"] / run["battle_count"], 1) if run["battle_count"] else 0,
            "battle_count": run["battle_count"],
            "status": run["status"],
            "error_type": run["error_msg"] or "",
        }
        for run in sorted(runs, key=lambda r: r["start"], reverse=True)
    ]

    success_rate = round(success / (success + failed) * 100, 1) if (success + failed) else 0.0
    avg_duration_minutes = round(total_duration / len(closed) / 60, 1) if closed else 0.0
    return {
        "script_name": script_name,
        "start": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "end": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "task": task_filter,
        "tasks": sorted({task_display_name(r["task"]) for r in runs}),
        "total_runs": len(runs),
        "success_runs": success,
        "failed_runs": failed,
        "running_runs": running,
        "success_rate": success_rate,
        "avg_duration_minutes": avg_duration_minutes,
        "total_battle_count": total_battles,
        "trend": trend_payload,
        "distribution": distribution_payload,
        "ranking": ranking_payload,
        "records": records,
    }
