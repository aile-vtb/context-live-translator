from __future__ import annotations

import queue
import threading
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from .cuda_runtime import register_cuda_dll_directories
from .i18n import tr
from .models import Recognition

INITIAL_PROMPTS: dict[str, str | None] = {
    "auto": None,
    "zh": "以下是台灣華語的自然口語內容。",
    "en": None,
    "ja": None,
    "ko": None,
    "yue": None,
}


def whisper_language_code(model: Any, requested_language: str) -> str | None:
    if requested_language == "auto":
        return None
    if requested_language != "yue":
        return requested_language
    tokenizer = getattr(model, "hf_tokenizer", None)
    if tokenizer is not None and tokenizer.token_to_id("<|yue|>") is not None:
        return "yue"
    return "zh"


def resolve_compute(device_setting: str, compute_setting: str) -> tuple[str, str]:
    if device_setting == "auto":
        try:
            import ctranslate2

            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        except Exception:
            device = "cpu"
    else:
        device = device_setting
    if compute_setting != "auto":
        return device, compute_setting
    return (device, "int8_float16") if device == "cuda" else (device, "int8")


def is_cuda_runtime_error(error: BaseException) -> bool:
    message = str(error).lower()
    markers = (
        "cuda",
        "cublas",
        "cudnn",
        "nvcuda",
        "nvrtc",
    )
    return any(marker in message for marker in markers)


def load_whisper_model(
    model_factory: Any,
    model_directory: Path,
    device: str,
    compute_type: str,
    allow_cpu_fallback: bool,
    on_status: Callable[[str], None],
) -> tuple[Any, str, str]:
    arguments = {
        "device": device,
        "compute_type": compute_type,
        "local_files_only": True,
    }
    try:
        return model_factory(str(model_directory), **arguments), device, compute_type
    except Exception as exc:
        if device == "cuda" and is_cuda_runtime_error(exc):
            if allow_cpu_fallback:
                on_status(
                    tr("Whisper CUDA 執行階段無法載入，已自動改用 CPU（不保證即時）")
                )
                return (
                    model_factory(
                        str(model_directory),
                        device="cpu",
                        compute_type="int8",
                        local_files_only=True,
                    ),
                    "cpu",
                    "int8",
                )
            raise RuntimeError(
                tr(
                    "CUDA 執行階段無法載入。請確認 llama-server.exe 與 cublas64_12.dll 位於同一資料夾，或執行 setup-gpu.cmd；也可將 Whisper 運算裝置改為 CPU。原始錯誤：{error}",
                    error=exc,
                )
            ) from exc
        raise


class SpeechWorker:
    def __init__(
        self,
        model_path: str,
        device: str,
        compute_type: str,
        on_result: Callable[[str, Recognition, float, float], None],
        on_status: Callable[[str], None],
        on_error: Callable[[str], None],
        cuda_library_paths: tuple[str, ...] = (),
    ) -> None:
        self.model_path = model_path
        self.device_setting = device
        self.compute_setting = compute_type
        self.on_result = on_result
        self.on_status = on_status
        self.on_error = on_error
        self.cuda_library_paths = cuda_library_paths
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._route_queues: dict[
            str, deque[tuple[np.ndarray, float, float, str]]
        ] = {}
        self._queue_lock = threading.Lock()
        self._max_pending_per_route = 4
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="whisper-worker")
        self._thread.start()

    def submit(
        self,
        route_id: str,
        audio: np.ndarray,
        started_at: float,
        ended_at: float,
        language: str,
    ) -> None:
        with self._queue_lock:
            route_queue = self._route_queues.setdefault(route_id, deque())
            if len(route_queue) >= self._max_pending_per_route:
                self.on_error(
                    tr(
                        "Whisper route「{route_id}」佇列已滿；已丟棄一段音訊以維持即時性",
                        route_id=route_id,
                    )
                )
                return
            needs_schedule = not route_queue
            route_queue.append((audio, started_at, ended_at, language))
            if needs_schedule:
                self._queue.put_nowait(route_id)

    def stop(self) -> None:
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass
        with self._queue_lock:
            self._route_queues.clear()
        self._queue.put_nowait(None)
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(8)
        self._thread = None

    def _run(self) -> None:
        try:
            register_cuda_dll_directories(self.cuda_library_paths)
            from faster_whisper import WhisperModel

            model_directory = Path(self.model_path)
            if not model_directory.is_dir():
                raise FileNotFoundError(tr("找不到本機 Whisper CTranslate2 模型目錄"))
            device, compute_type = resolve_compute(
                self.device_setting,
                self.compute_setting,
            )
            self.on_status(
                tr("載入 Whisper（{device}, {compute_type}）…", device=device, compute_type=compute_type)
            )
            model, device, compute_type = load_whisper_model(
                WhisperModel,
                model_directory,
                device,
                compute_type,
                self.device_setting == "auto",
                self.on_status,
            )
            self.on_status(
                tr("Whisper 已就緒（{device}, {compute_type}）", device=device, compute_type=compute_type)
            )
        except Exception as exc:
            self.on_error(tr("Whisper 載入失敗：{error}", error=exc))
            return
        reported_cantonese_fallback = False
        while True:
            scheduled_route = self._queue.get()
            if scheduled_route is None:
                return
            with self._queue_lock:
                route_queue = self._route_queues.get(scheduled_route)
                if not route_queue:
                    continue
                audio, started_at, ended_at, requested_language = route_queue.popleft()
                if route_queue:
                    self._queue.put_nowait(scheduled_route)
                else:
                    self._route_queues.pop(scheduled_route, None)
            route_id = scheduled_route
            try:
                model_language = whisper_language_code(model, requested_language)
                if (
                    requested_language == "yue"
                    and model_language == "zh"
                    and not reported_cantonese_fallback
                ):
                    self.on_status(tr("此 Whisper 模型沒有粵語 token，改用中文 token 辨識"))
                    reported_cantonese_fallback = True
                segment_iter, info = model.transcribe(
                    audio,
                    language=model_language,
                    initial_prompt=INITIAL_PROMPTS[requested_language],
                    beam_size=3,
                    vad_filter=False,
                    condition_on_previous_text=False,
                    word_timestamps=False,
                )
                segments = list(segment_iter)
                text = "".join(segment.text for segment in segments).strip()
                if not text:
                    continue
                weights = [max(1, len(segment.text.strip())) for segment in segments]
                total_weight = sum(weights)
                detected_language = (
                    str(getattr(info, "language", "") or model_language or "unknown").lower()
                )
                probability = float(
                    getattr(info, "language_probability", 1.0 if model_language else 0.0)
                )
                self.on_result(
                    route_id,
                    Recognition(
                        text=text,
                        language=(
                            requested_language
                            if requested_language != "auto"
                            else detected_language
                        ),
                        language_probability=probability,
                        avg_logprob=sum(
                            segment.avg_logprob * weight
                            for segment, weight in zip(segments, weights, strict=False)
                        )
                        / total_weight,
                        no_speech_prob=max(segment.no_speech_prob for segment in segments),
                        compression_ratio=max(segment.compression_ratio for segment in segments),
                    ),
                    started_at,
                    ended_at,
                )
            except Exception as exc:
                self.on_error(tr("Whisper 辨識失敗：{error}", error=exc))
