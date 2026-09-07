# This Python file uses the following encoding: utf-8
"""
操作分析接口：从脚本日志解析点击/滑动坐标，供热力图与时序回放。

路由（挂在 /analysis 前缀下）:
  GET /analysis/scripts                         实例列表
  GET /analysis/{script_name}/dates             有日志的日期列表
  GET /analysis/{script_name}?date=&task=       某天（可按任务过滤）的操作记录

数据来源: log/YYYY-MM-DD_<脚本名>.txt
  点击: `Click ( 811,  632) @ PAGE_MAIN_GOTO_DAILY` / `点击 (1186, 193) @ XXX`
  滑动: `Swipe (1204, 195) -> (1177, 334)` / `滑动 ( 611, 505) -> ( 615, 255)`
坐标全部位于 1280x720 游戏画面坐标系。
"""
from __future__ import annotations

import json
import re
import threading
from collections import defaultdict
from datetime import date as date_cls, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from module.server.api_logger import ApiLoggingRoute

PROJECT_ROOT = Path.cwd().resolve()
LOG_ROOT = (PROJECT_ROOT / "log").resolve()

_LOG_FILE_RE = re.compile(r"^(?P<day>\d{4}-\d{2}-\d{2})_(?P<script>.+)\.txt$")
_EXCLUDED_SCRIPTS = {"server", "api"}
_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\s+\|"
    r"\s*(?P<src>\S+)\s*\|\s*(?P<level>[A-Z]+)\s*\|\s?(?P<msg>.*)$"
)
_TASK_START_RE = re.compile(r"(?:Start task|开始任务)\s+`(?P<task>[A-Za-z0-9_]+)`")
_TASK_END_RE = re.compile(r"(?:End task|任务)\s+`(?P<task>[A-Za-z0-9_]+)`\s*(?:ended|结束)?")
_TASK_ENDED_LEGACY_RE = re.compile(r"^(?P<task>[A-Za-z0-9_]+)\s+task ended\b")
_CLICK_RE = re.compile(r"(?:Click|点击)\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)(?:\s*@\s*(?P<name>\S+))?")
_SWIPE_RE = re.compile(
    r"(?:Swipe|滑动)\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)\s*->\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)")
# 坐标日志来自 control.py，用来源过滤，避免把任务文本里的"点击XX"描述算进来
_CONTROL_SRC_RE = re.compile(r"(^|[\\/])control\.py")

CANVAS_WIDTH = 1280
CANVAS_HEIGHT = 720

analysis_app = APIRouter(
    prefix="/analysis",
    tags=["analysis"],
    route_class=ApiLoggingRoute,
)


class OperationItem(BaseModel):
    ts: str = Field(description="发生时间 HH:MM:SS.mmm")
    offset_ms: int = Field(description="相对所属运行段开始的毫秒数（回放用）")
    type: str = Field(description="click | swipe")
    x1: int
    y1: int
    x2: int | None = None
    y2: int | None = None
    name: str = Field(default="", description="控件名/目标名")
    task: str = Field(default="", description="所属任务 CamelCase 名，空为任务间隙")
    run_index: int = Field(default=0, description="该任务当天第几段运行（1 起，最新最大）")


class RunItem(BaseModel):
    task: str
    task_cn: str
    run_index: int
    start_time: str
    end_time: str
    start_iso: str
    end_iso: str
    duration_seconds: float
    click_count: int
    swipe_count: int
    failed: bool = Field(description="无操作且未正常结束的运行段")


class AnalysisDayResponse(BaseModel):
    script_name: str
    date: str
    canvas_width: int = CANVAS_WIDTH
    canvas_height: int = CANVAS_HEIGHT
    total_click_count: int
    total_swipe_count: int
    total_runtime_seconds: float
    tasks: list[str] = Field(description="当天出现过的任务 CamelCase 名（可作为 task= 过滤值）")
    runs: list[RunItem]
    operations: list[OperationItem]


class AnalysisScriptsResponse(BaseModel):
    scripts: list[str]


class AnalysisDatesResponse(BaseModel):
    script_name: str
    dates: list[str]


def list_scripts() -> list[str]:
    names: set[str] = set()
    if LOG_ROOT.exists():
        for f in LOG_ROOT.iterdir():
            m = _LOG_FILE_RE.match(f.name)
            if m and m.group("script") not in _EXCLUDED_SCRIPTS and not m.group("script").startswith("-"):
                names.add(m.group("script"))
    return sorted(names)


def list_dates(script_name: str) -> list[str]:
    dates: set[str] = set()
    if LOG_ROOT.exists():
        for f in LOG_ROOT.iterdir():
            m = _LOG_FILE_RE.match(f.name)
            if m and m.group("script") == script_name:
                dates.add(m.group("day"))
    dates.add(date_cls.today().isoformat())
    return sorted(dates, reverse=True)


def _script_files(script_name: str) -> list[Path]:
    if not LOG_ROOT.exists():
        return []
    return sorted(
        f for f in LOG_ROOT.iterdir()
        if _LOG_FILE_RE.match(f.name) and _LOG_FILE_RE.match(f.name).group("script") == script_name
    )


# 任务 CamelCase 名 -> 中文名（覆盖 OAS 全部调度任务）
TASK_NAME_CN = {
    "Restart": "重启",
    "GlobalGame": "全局配置",
    "Orochi": "八岐大蛇",
    "TrueOrochi": "真八岐大蛇",
    "OrochiMoans": "魂觉醒",
    "FallenSun": "日轮之陨",
    "EternitySea": "永生之海",
    "DailyTrifles": "每日琐事",
    "WeeklyTrifles": "每周琐事",
    "AreaBoss": "地域鬼王",
    "GoldYoukai": "金币妖怪",
    "ExperienceYoukai": "经验妖怪",
    "Nian": "年兽",
    "TalismanPass": "花合战",
    "DemonEncounter": "逢魔之时",
    "Pets": "小猫咪",
    "SoulsTidy": "御魂整理",
    "Delegation": "式神委派",
    "WantedQuests": "悬赏封印",
    "Tako": "石距",
    "BondlingFairyland": "契灵之境",
    "EvoZone": "觉醒副本",
    "GoryouRealm": "御灵之境",
    "Exploration": "探索",
    "KekkaiUtilize": "结界蹭卡",
    "KekkaiActivation": "结界挂卡",
    "RealmRaid": "个人突破",
    "RyouToppa": "寮突破",
    "CollectiveMissions": "集体任务",
    "Hunt": "狩猎战",
    "RichMan": "大富翁",
    "Secret": "秘闻副本",
    "MysteryShop": "神秘商店",
    "Duel": "斗技",
    "ActivityShikigami": "当期爬塔",
    "MetaDemon": "超鬼王",
    "MemoryScrolls": "绘卷",
    "DyeTrials": "灵染试炼",
    "Hyakkiyakou": "百鬼夜行",
    "Dokan": "道馆",
    "SixRealms": "六道之门",
    "FrogBoss": "对弈竞猜",
    "FloatParade": "花车巡游",
    "Quiz": "智力竞赛",
    "HeroTest": "英杰试炼",
    "AbyssShadows": "狭间暗域",
    "FindJade": "寻找协作任务",
    "GuildBanquet": "寮宴会",
    "KittyShop": "猫咪铺子",
    "GameUi": "界面切换",
    "GotoMain": "回到主页面",
    "GuildActivityMonitor": "寮活动监控",
    "GeneralInvite": "接受邀请",
    "AutoCheckinBigGod": "大神签到",
    "OtherWorldTwilight": "彼岸花海",
    "BudokaiTournament": "武道大会",
    "MartialTournament": "武林大会",
    "Slightly": "小事件",
    "Chess": "百鬼棋局",
    "NewbieStory": "新手剧情",
}

_I18N_LOCK = threading.Lock()


def task_display_name(task: str) -> str:
    return TASK_NAME_CN.get(task, task)


def _resolve_task_filter(task_filter: str) -> str:
    """把筛选值归一化为 CamelCase 任务名, 同时兼容中文与英文名。"""
    if not task_filter:
        return task_filter
    if task_filter in TASK_NAME_CN or True:
        if task_filter in TASK_NAME_CN:
            return task_filter
        for camel, cn in TASK_NAME_CN.items():
            if cn == task_filter:
                return camel
    return task_filter


def build_analysis(script_name: str, target_day: date_cls, task_filter: str = "") -> dict[str, Any]:
    """
    解析某天的点击/滑动操作。

    一天的日志可能分布在多个文件（跨天/重启），按行内时间戳归属；
    操作按运行段（任务串行窗口）归组，跨天段裁剪到目标日。
    """
    day_start = datetime.combine(target_day, datetime.min.time())
    day_end = datetime.combine(target_day, datetime.max.time())

    raw_runs: list[dict[str, Any]] = []  # {task, start, end|None, explicit_end}
    raw_ops: list[dict[str, Any]] = []   # {ts, type, x1, y1, x2|None, y2|None, name}
    for path in _script_files(script_name):
        current: dict[str, Any] | None = None
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            for raw in f:
                m = _LINE_RE.match(raw)
                if not m:
                    continue
                ts = _parse_ts(m.group("ts"))
                src, msg = m.group("src"), m.group("msg")

                ms_start = _TASK_START_RE.search(msg)
                if ms_start:
                    if current is not None and current["end"] is None:
                        current["end"] = ts
                    current = {"task": ms_start.group("task"), "start": ts, "end": None, "explicit_end": False}
                    raw_runs.append(current)
                    continue
                if current is not None:
                    me_end = _TASK_END_RE.search(msg) or _TASK_ENDED_LEGACY_RE.match(msg)
                    if me_end:
                        current["end"] = ts
                        current["explicit_end"] = True
                        current = None
                        continue

                if not _CONTROL_SRC_RE.search(src):
                    continue
                click = _CLICK_RE.search(msg)
                if click:
                    raw_ops.append({
                        "ts": ts, "type": "click",
                        "x1": int(click.group(1)), "y1": int(click.group(2)),
                        "x2": None, "y2": None,
                        "name": (click.group("name") or "").strip(),
                    })
                    continue
                swipe = _SWIPE_RE.search(msg)
                if swipe:
                    raw_ops.append({
                        "ts": ts, "type": "swipe",
                        "x1": int(swipe.group(1)), "y1": int(swipe.group(2)),
                        "x2": int(swipe.group(3)), "y2": int(swipe.group(4)),
                        "name": "",
                    })

    # 任务串行执行：未闭合运行段最晚在下一段任务开始时结束；
    # 文件末尾仍开放的段用当天末尾兜底（跨天场景会被裁剪）
    raw_runs.sort(key=lambda r: r["start"])
    fallback_end = datetime.combine(date_cls.today(), datetime.max.time())
    for i, run in enumerate(raw_runs):
        if run["end"] is not None:
            continue
        run["end"] = fallback_end
        for _, later in raw_runs[i + 1:]:
            if later["start"] > run["start"]:
                run["end"] = later["start"]
                run["explicit_end"] = False
                break

    runs = [
        r for r in raw_runs
        if r["end"] >= day_start and r["start"] <= day_end
    ]
    for run in runs:
        run["clip_start"] = max(run["start"], day_start)
        run["clip_end"] = min(run["end"], day_end)

    def _locate_run_index(op_ts: datetime) -> int:
        for idx, run in enumerate(runs):
            if run["clip_start"] <= op_ts <= run["clip_end"]:
                return idx
        return -1

    # 同任务按开始时间正序编号
    run_seq: dict[int, int] = {}
    seq_counter: dict[str, int] = defaultdict(int)
    for idx, run in enumerate(runs):  # runs 已按 start 正序
        seq_counter[run["task"]] += 1
        run_seq[idx] = seq_counter[run["task"]]

    per_run_counts: list[list[int]] = [[0, 0] for _ in runs]  # [click, swipe]
    operations: list[dict[str, Any]] = []
    task_names: set[str] = set()
    for op in raw_ops:
        if not (day_start <= op["ts"] <= day_end):
            continue
        run_idx = _locate_run_index(op["ts"])
        op_task = runs[run_idx]["task"] if run_idx >= 0 else ""
        if task_filter and op_task != task_filter:
            continue
        if run_idx >= 0:
            if op["type"] == "click":
                per_run_counts[run_idx][0] += 1
            else:
                per_run_counts[run_idx][1] += 1
            offset_ms = int((op["ts"] - runs[run_idx]["clip_start"]).total_seconds() * 1000)
        else:
            offset_ms = 0
        operations.append({
            "ts": op["ts"].strftime("%H:%M:%S.%f")[:-3],
            "offset_ms": offset_ms,
            "type": op["type"],
            "x1": op["x1"], "y1": op["y1"],
            "x2": op["x2"], "y2": op["y2"],
            "name": op.get("name") or "",
            "task": op_task,
            "run_index": run_seq[run_idx] if run_idx >= 0 else 0,
        })
        if op_task:
            task_names.add(op_task)
    operations.sort(key=lambda o: o["ts"])

    run_payloads: list[dict[str, Any]] = []
    for idx, run in enumerate(runs):
        if task_filter and run["task"] != task_filter:
            continue
        clicks, swipes = per_run_counts[idx]
        run_payloads.append({
            "task": run["task"],
            "task_cn": task_display_name(run["task"]),
            "run_index": run_seq[idx],
            "start_time": run["clip_start"].strftime("%H:%M:%S"),
            "end_time": run["clip_end"].strftime("%H:%M:%S"),
            "start_iso": run["clip_start"].isoformat(),
            "end_iso": run["clip_end"].isoformat(),
            "duration_seconds": round((run["clip_end"] - run["clip_start"]).total_seconds(), 1),
            "click_count": clicks,
            "swipe_count": swipes,
            "failed": (clicks == 0 and swipes == 0) and not run["explicit_end"],
        })
    run_payloads.sort(key=lambda r: r["start_iso"], reverse=True)

    # 倒序展示：最新一段编号最大
    total_seq: dict[str, int] = defaultdict(int)
    for run in run_payloads:
        total_seq[run["task"]] += 1
    for run in run_payloads:
        run["run_index"] = total_seq[run["task"]]
        total_seq[run["task"]] -= 1

    return {
        "script_name": script_name,
        "date": target_day.isoformat(),
        "canvas_width": CANVAS_WIDTH,
        "canvas_height": CANVAS_HEIGHT,
        "total_click_count": sum(1 for o in operations if o["type"] == "click"),
        "total_swipe_count": sum(1 for o in operations if o["type"] == "swipe"),
        "total_runtime_seconds": round(sum(r["duration_seconds"] for r in run_payloads), 1),
        "tasks": sorted(task_names),
        "runs": run_payloads,
        "operations": operations,
    }


_TS_PARSE_CACHE: dict[str, datetime] = {}


def _parse_ts(text: str) -> datetime:
    dt = _TS_PARSE_CACHE.get(text)
    if dt is None:
        dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S.%f")
        _TS_PARSE_CACHE[text] = dt
    return dt


def _parse_op_ts(text: str) -> datetime:
    dt = _TS_PARSE_CACHE.get(text)
    if dt is None:
        dt = datetime.strptime(f"2000-01-01 {text}", "%Y-%m-%d %H:%M:%S.%f")
        _TS_PARSE_CACHE[text] = dt
    return dt


def _parse_target_date(date_text: str) -> date_cls:
    try:
        return datetime.strptime(date_text, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid date format, expected YYYY-MM-DD") from exc


@analysis_app.get("/scripts", response_model=AnalysisScriptsResponse)
async def analysis_scripts():
    return AnalysisScriptsResponse(scripts=list_scripts())


@analysis_app.get("/{script_name}/dates", response_model=AnalysisDatesResponse)
async def analysis_dates(script_name: str):
    return AnalysisDatesResponse(script_name=script_name, dates=list_dates(script_name))


@analysis_app.get("/{script_name}", response_model=AnalysisDayResponse)
async def analysis_day(
    script_name: str,
    date_text: str = Query(..., alias="date", description="YYYY-MM-DD"),
    task: str = Query(default="", description="按任务 CamelCase 名过滤"),
):
    target_day = _parse_target_date(date_text)
    return build_analysis(
        script_name, target_day, task_filter=_resolve_task_filter(task)
    )
