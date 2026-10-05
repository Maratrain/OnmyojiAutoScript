# This Python file uses the following encoding: utf-8
"""
OAS 日志分析器：页面托管 + 日志文件读取接口。

路由（挂在 /log_analyzer 前缀下）:
  GET /log_analyzer/page                 分析器页面
  GET /log_analyzer/api/logs             可分析的日志文件列表
  GET /log_analyzer/api/log?file=...     读取单份日志全文（纯文本）

数据来源: log/YYYY-MM-DD_<脚本名>.txt。
解析在前端完成（module/server/web/log_analyzer/static/parser.js），
错误截图关联复用 /logs/errors/* 接口，这里不做业务聚合。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from module.server.api_logger import ApiLoggingRoute

PROJECT_ROOT = Path.cwd().resolve()
LOG_ROOT = (PROJECT_ROOT / "log").resolve()
WEB_DIR = Path(__file__).resolve().parent / "web" / "log_analyzer"

# 与 analysis_router / task_statistics_router 保持一致的日志文件名规则
_LOG_FILE_RE = re.compile(r"^(?P<day>\d{4}-\d{2}-\d{2})_(?P<script>.+)\.txt$")
# 单份日志全文读取上限（day 级日志实测约 6MB/天，64MB 已留足余量）
MAX_LOG_BYTES = 64 * 1024 * 1024

log_analyzer_app = APIRouter(
    prefix="/log_analyzer",
    tags=["log_analyzer"],
    route_class=ApiLoggingRoute,
)


class LogFileItem(BaseModel):
    """日志文件列表中的单个条目。"""

    file: str = Field(description="日志文件名, 也是 /api/log 的 file 参数")
    script: str = Field(description="脚本实例名")
    date: str = Field(description="日志日期 YYYY-MM-DD")
    size: int = Field(description="文件字节数")


class LogFileListResponse(BaseModel):
    """日志文件列表响应。"""

    items: list[LogFileItem] = Field(default_factory=list, description="按日期倒序的日志文件列表")


def _iter_log_files() -> list[LogFileItem]:
    """扫描 log 目录下的日级日志文件。"""
    items: list[LogFileItem] = []
    if not LOG_ROOT.is_dir():
        return items
    for entry in LOG_ROOT.iterdir():
        if not entry.is_file():
            continue
        matched = _LOG_FILE_RE.match(entry.name)
        if not matched:
            continue
        items.append(
            LogFileItem(
                file=entry.name,
                script=matched.group("script"),
                date=matched.group("day"),
                size=entry.stat().st_size,
            )
        )
    items.sort(key=lambda x: (x.date, x.script), reverse=True)
    return items


@log_analyzer_app.get("/page")
async def analyzer_page() -> FileResponse:
    """返回分析器页面。"""
    index_file = WEB_DIR / "index.html"
    if not index_file.is_file():
        raise HTTPException(status_code=404, detail="log_analyzer 页面文件缺失")
    return FileResponse(index_file)


@log_analyzer_app.get("/api/logs", response_model=LogFileListResponse)
async def list_logs() -> LogFileListResponse:
    """列出可分析的日志文件。"""
    return LogFileListResponse(items=_iter_log_files())


@log_analyzer_app.get("/api/log")
async def read_log(file: str = Query(description="日志文件名, 来自 /api/logs 的 file 字段")) -> PlainTextResponse:
    """读取单份日志全文，解析工作全部在前端完成。"""
    if not _LOG_FILE_RE.match(file) or "/" in file or "\\" in file or ".." in file:
        raise HTTPException(status_code=400, detail="非法的日志文件名")
    target = (LOG_ROOT / file).resolve()
    if not str(target).startswith(str(LOG_ROOT)):
        raise HTTPException(status_code=400, detail="非法的日志路径")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="日志文件不存在")
    if target.stat().st_size > MAX_LOG_BYTES:
        raise HTTPException(status_code=413, detail="日志文件过大, 超过 64MB 读取上限")
    content = target.read_text(encoding="utf-8", errors="replace")
    return PlainTextResponse(content, media_type="text/plain; charset=utf-8")
