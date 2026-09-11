# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from __future__ import annotations

import atexit
import hashlib
import multiprocessing
import pickle
import socket
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np
import zerorpc

from module.exception import ScriptError
from module.logger import logger
from module.ocr.ppocr import TextSystem

# OCR 服务始终通过全新解释器启动，避免继承父进程中已初始化的 RPC 运行时状态。
_OCR_SERVER_CONTEXT = multiprocessing.get_context("spawn")
_OCR_SERVER_PROCESS: Optional[multiprocessing.Process] = None
_OCR_CLIENT_CACHE: dict[str, "ModelProxy"] = {}
# 脚本进程级 OCR 低配模式：延长请求超时并启用短期结果缓存。
_OCR_LOW_SPEC_MODE: bool = False


def set_ocr_low_spec_mode(enabled: bool) -> None:
    """设置当前脚本进程的 OCR 低配模式。"""
    global _OCR_LOW_SPEC_MODE
    _OCR_LOW_SPEC_MODE = bool(enabled)


class _OcrResultCache:
    """短期 OCR 结果缓存，低配模式下减少对同一画面的重复识别。"""

    def __init__(self, max_size: int = 16, ttl_seconds: float = 2.0) -> None:
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds
        self._entries: OrderedDict[tuple[Any, ...], tuple[float, Any]] = OrderedDict()

    def get(self, key: tuple[Any, ...]):
        entry = self._entries.get(key)
        if entry is None:
            return None
        created_at, value = entry
        if time.monotonic() - created_at >= self._ttl_seconds:
            self._entries.pop(key, None)
            return None
        self._entries.move_to_end(key)
        return value

    def put(self, key: tuple[Any, ...], value: Any) -> None:
        self._entries[key] = (time.monotonic(), value)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_size:
            self._entries.popitem(last=False)


def _normalize_address(address: str) -> str:
    if address.startswith("tcp://"):
        return address
    return f"tcp://{address}"


def _split_host_port(address: str) -> tuple[str, int]:
    addr = address.replace("tcp://", "")
    if ":" not in addr:
        return addr, 22268
    host, port = addr.rsplit(":", 1)
    return host, int(port)


def _is_port_in_use(host: str, port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(0.5)
        sock.connect((host, port))
        sock.shutdown(2)
        return True
    except Exception:
        return False
    finally:
        sock.close()


@dataclass(slots=True)
class OcrServerSettings:
    worker_count: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "OcrServerSettings":
        if not data:
            return cls()
        return cls(worker_count=int(data.get("worker_count", 0)))


class OcrTaskScheduler:
    def __init__(self, worker_count: int = 0) -> None:
        self.worker_count = max(1, worker_count or (multiprocessing.cpu_count() or 1))
        self._executor = ThreadPoolExecutor(
            max_workers=self.worker_count,
            thread_name_prefix="ocr_worker",
        )
        self._pending_lock = threading.Lock()
        self._pending = 0

    def submit(self, func, *args, **kwargs):
        with self._pending_lock:
            self._pending += 1
        future = self._executor.submit(func, *args, **kwargs)
        future.add_done_callback(self._on_done)
        return future

    def stats(self) -> dict[str, int]:
        with self._pending_lock:
            pending = self._pending
        return {
            "worker_count": self.worker_count,
            "pending": pending,
        }

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _on_done(self, _future) -> None:
        with self._pending_lock:
            self._pending = max(0, self._pending - 1)


class OcrRuntime:
    def __init__(self, settings: dict[str, Any] | OcrServerSettings | None = None) -> None:
        if isinstance(settings, OcrServerSettings):
            self.settings = settings
        else:
            self.settings = OcrServerSettings.from_dict(settings)
        self._scheduler = OcrTaskScheduler(self.settings.worker_count)
        self._thread_local = threading.local()
        self._lock = threading.Lock()
        self._loaded_workers: set[str] = set()
        self._request_stats = {
            "requests_total": 0,
            "requests_succeeded": 0,
            "requests_failed": 0,
        }
        logger.info(f"[OCR] 运行时初始化完成 (workers={self._scheduler.worker_count})")

    def ping(self) -> bool:
        return True

    def get_server_info(self) -> dict[str, Any]:
        with self._lock:
            request_stats = dict(self._request_stats)
            loaded_worker_count = len(self._loaded_workers)
        return {
            "scheduler": self._scheduler.stats(),
            "request_stats": request_stats,
            "loaded_worker_count": loaded_worker_count,
        }

    def warmup(self) -> bool:
        """在接受请求前先在工作线程加载模型。"""
        logger.info('[OCR] 正在预热 OCR 模型')
        future = self._scheduler.submit(self._get_model)
        future.result()
        logger.info('[OCR] 模型预热完成')
        return True

    def ocr_single_line(self, image_bytes: bytes):
        image = self._decode_image(image_bytes)
        return self._run_request(self._ocr_single_line, image)

    def detect_and_ocr(
        self,
        image_bytes: bytes,
        drop_score: float = 0.5,
        unclip_ratio: Optional[float] = None,
        box_thresh: Optional[float] = None,
        vertical: bool = False,
    ) -> List[Dict[str, Any]]:
        image = self._decode_image(image_bytes)
        return self._run_request(
            self._detect_and_ocr,
            image,
            drop_score=drop_score,
            unclip_ratio=unclip_ratio,
            box_thresh=box_thresh,
            vertical=vertical,
        )

    def shutdown(self) -> bool:
        self._scheduler.shutdown()
        return True

    def _run_request(self, func, *args, **kwargs):
        with self._lock:
            self._request_stats["requests_total"] += 1
        future = self._scheduler.submit(func, *args, **kwargs)
        try:
            result = future.result()
        except Exception:
            with self._lock:
                self._request_stats["requests_failed"] += 1
            raise
        with self._lock:
            self._request_stats["requests_succeeded"] += 1
        return result

    @staticmethod
    def _decode_image(image_bytes: bytes) -> np.ndarray:
        image = pickle.loads(image_bytes)
        if not isinstance(image, np.ndarray):
            raise TypeError("OCR payload must be numpy.ndarray")
        return image

    @staticmethod
    def _rotate_vertical(image: np.ndarray) -> np.ndarray:
        height, width = image.shape[0:2]
        if width == 0:
            return image
        if height * 1.0 / width >= 1.5:
            return np.rot90(image)
        return image

    def _get_model(self) -> TextSystem:
        model = getattr(self._thread_local, "model", None)
        if model is None:
            model = TextSystem()
            self._thread_local.model = model
            worker_name = threading.current_thread().name
            with self._lock:
                self._loaded_workers.add(worker_name)
            logger.info(f"[OCR] 工作线程模型加载完成: {worker_name}")
        return model

    def _ocr_single_line(self, image: np.ndarray):
        model = self._get_model()
        result, score = model.ocr_single_line(image)
        return result, float(score)

    def _detect_and_ocr(
        self,
        image: np.ndarray,
        drop_score: float = 0.5,
        unclip_ratio: Optional[float] = None,
        box_thresh: Optional[float] = None,
        vertical: bool = False,
    ) -> List[Dict[str, Any]]:
        model = self._get_model()
        if vertical:
            results = self._detect_and_ocr_vertical(
                model,
                image,
                drop_score=drop_score,
                unclip_ratio=unclip_ratio,
                box_thresh=box_thresh,
            )
        else:
            results = model.detect_and_ocr(
                image,
                drop_score=drop_score,
                unclip_ratio=unclip_ratio,
                box_thresh=box_thresh,
            )
        return [
            {"box": item.box.tolist(), "ocr_text": item.ocr_text, "score": float(item.score)}
            for item in results
        ]

    def _detect_and_ocr_vertical(
        self,
        model: TextSystem,
        image: np.ndarray,
        drop_score: float = 0.5,
        unclip_ratio: Optional[float] = None,
        box_thresh: Optional[float] = None,
    ) -> list[Any]:
        text_recognizer = model.text_recognizer

        def vertical_text_recognizer(img_crop_list):
            img_crop_list = [self._rotate_vertical(item) for item in img_crop_list]
            return text_recognizer(img_crop_list)

        model.text_recognizer = vertical_text_recognizer
        try:
            return model.detect_and_ocr(
                image,
                drop_score=drop_score,
                unclip_ratio=unclip_ratio,
                box_thresh=box_thresh,
            )
        finally:
            model.text_recognizer = text_recognizer


def _build_server_settings() -> dict[str, Any]:
    from module.server.setting import State

    deploy_config = State.deploy_config
    return {
        "worker_count": int(deploy_config.OcrServerWorkerCount),
    }


def ensure_ocr_server_started() -> bool:
    from module.server.setting import State

    deploy_config = State.deploy_config
    if not deploy_config.StartOcrServer:
        return False

    if deploy_config.OcrServerPort:
        port = int(deploy_config.OcrServerPort)
    else:
        _, port = _split_host_port(str(deploy_config.OcrClientAddress))
    host = "0.0.0.0"

    if _is_port_in_use("127.0.0.1", port):
        logger.info(f"[OCR] 服务已在端口 {port} 运行")
        return True

    global _OCR_SERVER_PROCESS
    if _OCR_SERVER_PROCESS is not None and _OCR_SERVER_PROCESS.is_alive():
        logger.info("[OCR] 服务进程已启动")
        return True

    _OCR_SERVER_PROCESS = _OCR_SERVER_CONTEXT.Process(
        target=run_ocr_server,
        args=(host, port, _build_server_settings()),
        name="ocr_server",
        daemon=True,
    )
    _OCR_SERVER_PROCESS.start()
    logger.info(f"[OCR] 正在启动 OCR 服务: {host}:{port}")
    for _ in range(50):
        if _is_port_in_use("127.0.0.1", port):
            return True
        time.sleep(0.1)
    logger.error(f"[OCR] 服务未在端口 {port} 就绪")
    return False


def ensure_ocr_server_ready() -> bool:
    from module.server.setting import State

    deploy_config = State.deploy_config
    if deploy_config.StartOcrServer:
        ensure_ocr_server_started()

    address = deploy_config.OcrClientAddress or "127.0.0.1:22268"
    try:
        get_ocr_client(address=address, refresh=True)
        logger.info(f"[OCR] 服务已就绪: {address}")
        return True
    except Exception as exc:
        raise ScriptError(f"OCR server connection failed: {address}") from exc


def shutdown_ocr_server(timeout: float = 2.0) -> bool:
    global _OCR_SERVER_PROCESS

    process = _OCR_SERVER_PROCESS
    if process is None:
        return False

    if not process.is_alive():
        _OCR_SERVER_PROCESS = None
        return False

    logger.info("[OCR] 正在停止 OCR 服务进程")
    try:
        process.terminate()
        process.join(timeout=timeout)
        if process.is_alive():
            logger.warning("[OCR] 服务进程未按时退出，强制结束")
            process.kill()
            process.join(timeout=1.0)
        logger.info("[OCR] 服务进程已停止")
        return True
    except Exception as e:
        logger.exception(e)
        return False
    finally:
        _OCR_SERVER_PROCESS = None
        _OCR_CLIENT_CACHE.clear()


def run_ocr_server(host: str, port: int, settings: dict[str, Any] | None = None) -> None:
    runtime = OcrRuntime(settings=settings)
    server = zerorpc.Server(runtime)
    try:
        server.bind(f"tcp://{host}:{port}")
        server.run()
    finally:
        runtime.shutdown()


class ModelProxy:
    def __init__(self, address: str) -> None:
        self.address = _normalize_address(address)
        # 低配模式下 OCR 请求耗时更长，使用更大的超时并启用短期结果缓存。
        timeout = 30.0 if _OCR_LOW_SPEC_MODE else 10.0
        self.client = zerorpc.Client(timeout=timeout)
        self._cache = _OcrResultCache() if _OCR_LOW_SPEC_MODE else None
        try:
            self.client.connect(self.address)
            self.client.ping()
        except Exception as e:
            raise ScriptError(f"OCR server connection failed: {self.address}") from e

    def ping(self) -> bool:
        return bool(self.client.ping())

    def warmup(self) -> bool:
        """请求 OCR 服务预热模型。"""
        return bool(self.client.warmup())

    def get_server_info(self) -> dict[str, Any]:
        return self.client.get_server_info()

    def ocr_single_line(self, image: np.ndarray):
        payload = pickle.dumps(image, protocol=4)
        if self._cache is not None:
            key = ('ocr_single_line', hashlib.sha1(payload).hexdigest())
            cached = self._cache.get(key)
            if cached is not None:
                return cached
            result = self.client.ocr_single_line(payload)
            self._cache.put(key, result)
            return result
        return self.client.ocr_single_line(payload)

    def detect_and_ocr(
        self,
        image: np.ndarray,
        drop_score: float = 0.5,
        unclip_ratio: Optional[float] = None,
        box_thresh: Optional[float] = None,
        vertical: bool = False,
    ):
        payload = pickle.dumps(image, protocol=4)
        if self._cache is not None:
            key = (
                'detect_and_ocr',
                hashlib.sha1(payload).hexdigest(),
                drop_score,
                unclip_ratio,
                box_thresh,
                vertical,
            )
            cached = self._cache.get(key)
            if cached is not None:
                return cached
            results = self.client.detect_and_ocr(payload, drop_score, unclip_ratio, box_thresh, vertical)
            self._cache.put(key, results)
        else:
            results = self.client.detect_and_ocr(payload, drop_score, unclip_ratio, box_thresh, vertical)
        from ppocronnx.predict_system import BoxedResult
        return [
            BoxedResult(np.array(item["box"]), None, item["ocr_text"], item["score"])
            for item in results
        ]


def get_ocr_client(address: str | None = None, refresh: bool = False) -> ModelProxy:
    from module.server.setting import State

    resolved_address = address or State.deploy_config.OcrClientAddress or "127.0.0.1:22268"
    if refresh or resolved_address not in _OCR_CLIENT_CACHE:
        _OCR_CLIENT_CACHE[resolved_address] = ModelProxy(resolved_address)
    return _OCR_CLIENT_CACHE[resolved_address]


atexit.register(shutdown_ocr_server)
