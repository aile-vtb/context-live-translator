from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from .i18n import tr
from .models import (
    RevisionItem,
    RevisionRequest,
    RevisionResult,
    TranscriptSegment,
)
from .text_processing import normalize_taiwan_chinese


def decode_json_content(content: Any) -> Any:
    if isinstance(content, (dict, list)):
        return content
    if not isinstance(content, str):
        raise ValueError(tr("模型回應不是文字或 JSON 物件"))
    stripped = content.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as original_error:
        starts = [position for position in (stripped.find("{"), stripped.find("[")) if position >= 0]
        if starts:
            start = min(starts)
            end = max(stripped.rfind("}"), stripped.rfind("]"))
            if end > start:
                try:
                    return json.loads(stripped[start : end + 1])
                except json.JSONDecodeError:
                    pass
        raise ValueError(tr("模型回應不含有效 JSON")) from original_error


def model_profile(model_path: str) -> str:
    name = Path(model_path).name.lower()
    if "gemma" in name:
        return "gemma"
    if "qwen" in name:
        return "qwen"
    return "generic"


def translation_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"translation": {"type": "string", "minLength": 1}},
        "required": ["translation"],
        "additionalProperties": False,
    }


def revision_schema(ids: tuple[str, ...]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "minItems": len(ids),
                "maxItems": len(ids),
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "enum": list(ids)},
                        "corrected_source_text": {"type": "string", "minLength": 1},
                        "translation": {"type": "string", "minLength": 1},
                    },
                    "required": ["id", "corrected_source_text", "translation"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    }


def validate_translation(payload: Any) -> str:
    if not isinstance(payload, dict):
        raise ValueError(tr("翻譯回應不是 JSON 物件"))
    translation = payload.get("translation")
    if not isinstance(translation, str) or not translation.strip():
        raise ValueError(tr("翻譯回應缺少 translation"))
    return translation.strip()


def validate_revision(payload: Any, expected_ids: tuple[str, ...]) -> tuple[RevisionItem, ...]:
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError(tr("回修回應缺少 items"))
    raw_items = payload["items"]
    if len(raw_items) != len(expected_ids):
        raise ValueError(tr("回修回應的字幕數量不符"))
    actual_ids = tuple(item.get("id") for item in raw_items if isinstance(item, dict))
    if actual_ids != expected_ids:
        raise ValueError(tr("回修回應必須保留原 ID 與順序"))
    result: list[RevisionItem] = []
    for item in raw_items:
        source = item.get("corrected_source_text")
        translation = item.get("translation")
        if not isinstance(source, str) or not source.strip():
            raise ValueError(tr("回修回應缺少 corrected_source_text"))
        if not isinstance(translation, str) or not translation.strip():
            raise ValueError(tr("回修回應缺少 translation"))
        result.append(RevisionItem(item["id"], source.strip(), translation.strip()))
    return tuple(result)


class LlamaServer:
    def __init__(
        self,
        executable: str,
        model: str,
        gpu_layers: int = 99,
        context: int = 4096,
        port: int = 8081,
    ) -> None:
        self.executable = executable
        self.model = model
        self.gpu_layers = gpu_layers
        self.context = context
        self.port = port
        self.process: subprocess.Popen[str] | None = None
        self._lock = threading.RLock()
        self._shutdown_requested = threading.Event()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def validate(self) -> None:
        if not Path(self.executable).is_file():
            raise FileNotFoundError(tr("找不到 llama-server.exe"))
        if not Path(self.model).is_file():
            raise FileNotFoundError(tr("找不到本機 GGUF 模型"))

    def start(self, timeout: float = 90) -> None:
        with self._lock:
            if self._shutdown_requested.is_set():
                raise RuntimeError(tr("llama-server 已停止；不會在 session 結束後重新啟動"))
            self.validate()
            if self.process and self.process.poll() is None:
                return
            try:
                if (
                    httpx.get(
                        f"{self.base_url}/health",
                        timeout=1,
                        trust_env=False,
                    ).status_code
                    == 200
                ):
                    raise RuntimeError(
                        tr(
                            "連接埠 {port} 已有 llama-server；請先關閉它或更換連接埠",
                            port=self.port,
                        )
                    )
            except httpx.HTTPError:
                pass
            command = [
                self.executable,
                "--model",
                self.model,
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--ctx-size",
                str(self.context),
                "--n-gpu-layers",
                str(self.gpu_layers),
                "--parallel",
                "2",
                "--batch-size",
                "256",
            ]
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            self.process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                creationflags=creationflags,
            )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            process = self.process
            if process is None or process.poll() is not None:
                raise RuntimeError(tr("llama-server 啟動後立即結束"))
            try:
                if (
                    httpx.get(
                        f"{self.base_url}/health",
                        timeout=1,
                        trust_env=False,
                    ).status_code
                    == 200
                ):
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.4)
        self.stop()
        raise TimeoutError(tr("llama-server 未在期限內就緒"))

    def stop(self) -> None:
        self._shutdown_requested.set()
        with self._lock:
            process, self.process = self.process, None
        if not process or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass


class StructuredLlamaClient:
    """Model-neutral llama.cpp client with Gemma and Qwen compatibility profiles."""

    def __init__(self, server: LlamaServer, on_status: Callable[[str], None]) -> None:
        self.server = server
        self.on_status = on_status
        self.profile = model_profile(server.model)
        self._structured_mode = "json_object" if self.profile == "gemma" else "json_schema"
        self._mode_lock = threading.Lock()

    def request_json(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        max_tokens: int,
    ) -> Any:
        self.server.start()
        with self._mode_lock:
            first_mode = self._structured_mode
        modes = [first_mode]
        if first_mode == "json_schema":
            modes.append("json_object")
        payload: dict[str, Any] = {
            "model": "local",
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": max_tokens,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        for mode in modes:
            if mode == "json_schema":
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "structured_output", "schema": schema},
                }
            else:
                payload["response_format"] = {"type": "json_object"}
            response = httpx.post(
                f"{self.server.base_url}/v1/chat/completions",
                json=payload,
                timeout=45,
                trust_env=False,
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError:
                if mode == "json_schema" and response.status_code == 400:
                    with self._mode_lock:
                        self._structured_mode = "json_object"
                    self.on_status(
                        tr(
                            "{profile} 不接受 JSON Schema，已切換為 JSON object 相容模式",
                            profile=self.profile,
                        )
                    )
                    continue
                raise
            with self._mode_lock:
                self._structured_mode = mode
            content = response.json()["choices"][0]["message"]["content"]
            return decode_json_content(content)
        raise RuntimeError(tr("沒有可用的結構化輸出模式"))

    def translate(self, segment: TranscriptSegment) -> str:
        target = segment.target_language
        extra = f"\nTarget-specific instruction: {target.instruction}" if target.instruction else ""
        system = (
            "You are a local live-transcription translator. Translate faithfully and concisely. "
            "Use natural spoken wording, preserve names, and do not explain, censor, or add facts. "
            'Return exactly one JSON object shaped as {"translation":"translated text"}.'
            f"{extra}"
        )
        prompt = (
            f"Speaker/source route: {segment.route_label} ({segment.route_id})\n"
            f"Source language: {segment.source_language}\n"
            f"Target language: {target.code} ({target.display_name})\n"
            f"Source text:\n{segment.source_text}"
        )
        decoded = self.request_json(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            translation_schema(),
            384,
        )
        result = validate_translation(decoded)
        return normalize_taiwan_chinese(result) if target.code == "zh-TW" else result

    def revise(self, request: RevisionRequest) -> RevisionResult:
        ids = tuple(segment.id for segment in request.mutable_segments)
        target = request.target_language
        locked = (
            "(none)"
            if request.locked_context is None
            else (
                f"[{request.locked_context.route_label}] "
                f"{request.locked_context.source_language}: "
                f"{request.locked_context.source_text} => "
                f"{request.locked_context.translation}"
            )
        )
        mutable_payload = [
            {
                "id": segment.id,
                "route_id": segment.route_id,
                "route_label": segment.route_label,
                "source_language": segment.source_language,
                "raw_asr_text": segment.raw_asr_text,
                "current_corrected_source_text": segment.source_text,
                "current_translation": segment.translation,
                "asr_language_probability": segment.language_probability,
                "asr_avg_logprob": segment.avg_logprob,
            }
            for segment in request.mutable_segments
        ]
        instruction = (
            "You revise recent live transcripts using textual context. Make only conservative, "
            "context-supported corrections to likely ASR mistakes; never invent missing speech. "
            "Preserve every supplied id and its order. Return all mutable items, even unchanged "
            "ones. Translate each corrected source into the same target language. "
            f"Target: {target.code} ({target.display_name}). {target.instruction}"
        )
        expected_shape = {
            "items": [
                {
                    "id": segment.id,
                    "corrected_source_text": "...",
                    "translation": "...",
                }
                for segment in request.mutable_segments
            ]
        }
        instruction += (
            " Return exactly one JSON object with this shape and these exact ids: "
            f"{json.dumps(expected_shape, ensure_ascii=False)}"
        )
        prompt = (
            f"Previous locked context:\n{locked}\n\n"
            "Mutable items:\n"
            f"{json.dumps(mutable_payload, ensure_ascii=False)}"
        )
        decoded = self.request_json(
            [
                {"role": "system", "content": instruction},
                {"role": "user", "content": prompt},
            ],
            revision_schema(ids),
            max(512, 320 * len(ids)),
        )
        items = list(validate_revision(decoded, ids))
        if target.code == "zh-TW":
            items = [
                RevisionItem(item.id, item.corrected_source_text, normalize_taiwan_chinese(item.translation))
                for item in items
            ]
        return RevisionResult(request.generation, tuple(items))


class TranslationWorker:
    def __init__(
        self,
        client: StructuredLlamaClient,
        on_result: Callable[[TranscriptSegment], None],
        on_status: Callable[[str], None],
    ) -> None:
        self.client = client
        self.on_result = on_result
        self.on_status = on_status
        self._queue: queue.Queue[TranscriptSegment | None] = queue.Queue(maxsize=8)
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="translation-worker")
        self._thread.start()

    def submit(self, segment: TranscriptSegment) -> None:
        try:
            self._queue.put_nowait(segment)
        except queue.Full:
            segment.error = tr("初譯佇列已滿")
            self.on_result(segment)

    def stop(self) -> None:
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass
        self._queue.put_nowait(None)
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(8)
        self._thread = None

    def _run(self) -> None:
        while True:
            segment = self._queue.get()
            if segment is None:
                return
            started = time.perf_counter()
            last_error: Exception | None = None
            for attempt in range(3):
                try:
                    segment.translation = self.client.translate(segment)
                    segment.error = None
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt < 2:
                        time.sleep(0.5 * (attempt + 1))
            else:
                segment.error = tr("翻譯失敗：{error}", error=last_error)
            segment.translation_latency_ms = round((time.perf_counter() - started) * 1000)
            self.on_result(segment)


class ContextRevisionWorker:
    def __init__(
        self,
        client: StructuredLlamaClient,
        on_result: Callable[[RevisionResult], None],
        on_error: Callable[[int, str], None],
    ) -> None:
        self.client = client
        self.on_result = on_result
        self.on_error = on_error
        self._queue: queue.Queue[RevisionRequest | None] = queue.Queue(maxsize=1)
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="revision-worker")
        self._thread.start()

    def submit(self, request: RevisionRequest) -> None:
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass
        self._queue.put_nowait(request)

    def stop(self) -> None:
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass
        self._queue.put_nowait(None)
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(8)
        self._thread = None

    def _run(self) -> None:
        while True:
            request = self._queue.get()
            if request is None:
                return
            try:
                self.on_result(self.client.revise(request))
            except Exception as exc:
                self.on_error(
                    request.generation,
                    tr("上下文回修失敗：{error}", error=exc),
                )
