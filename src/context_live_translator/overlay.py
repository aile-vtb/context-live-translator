from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from importlib.resources import files
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from .config import AppConfig
from .models import TranscriptSegment

OVERLAY_HOST = "127.0.0.1"


def overlay_url(port: int) -> str:
    return f"http://{OVERLAY_HOST}:{port}/overlay"


def overlay_style(config: AppConfig) -> dict[str, Any]:
    return {
        "show_source": config.obs_overlay_show_source,
        "font_family": config.obs_overlay_font_family,
        "translation_size": config.obs_overlay_translation_size,
        "source_size": config.obs_overlay_source_size,
        "text_color": config.obs_overlay_text_color,
        "source_color": config.obs_overlay_source_color,
        "background": config.obs_overlay_background,
        "outline_color": config.obs_overlay_outline_color,
        "outline_px": config.obs_overlay_outline_px,
        "position": config.obs_overlay_position,
        "text_align": config.obs_overlay_text_align,
        "width_percent": config.obs_overlay_width_percent,
    }


def segment_payload(segment: TranscriptSegment) -> dict[str, Any] | None:
    if not segment.translation:
        return None
    return {
        "id": segment.id,
        "started_at": segment.started_at,
        "source_language": segment.source_language,
        "source_text": segment.source_text,
        "target_language": segment.target_language.display_name,
        "translation": segment.translation,
        "status": segment.status.value,
        "revision": segment.revision,
        "source_language_uncertain": segment.source_language_uncertain,
        "route_id": segment.route_id,
        "route_label": segment.route_label,
        "context_group_id": segment.context_group_id,
        "generation": segment.generation,
        "last_updated_at": segment.last_updated_at,
    }


class OverlayServer:
    """Local-only HTTP/WebSocket server used by an OBS Browser Source."""

    def __init__(
        self,
        port: int = 8765,
        max_lines: int = 3,
        style: dict[str, Any] | None = None,
    ) -> None:
        self.port = port
        self.max_lines = max(1, min(8, int(max_lines)))
        self.app = FastAPI(
            title="Context Live Translator OBS Overlay",
            docs_url=None,
            redoc_url=None,
            openapi_url=None,
        )
        self._style = dict(style or {})
        self._segments: dict[str, dict[str, Any]] = {}
        self._clients: set[WebSocket] = set()
        self._state_lock = threading.RLock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._stop_requested = threading.Event()
        self._error: BaseException | None = None
        self._sequence = 0
        self._configure_routes()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and self._server)

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def snapshot(self) -> dict[str, Any]:
        with self._state_lock:
            return {
                "type": "snapshot",
                "segments": [dict(item) for item in self._ordered_segments()],
                "style": dict(self._style),
                "sequence": self._sequence,
            }

    def _configure_routes(self) -> None:
        @self.app.get("/overlay", response_class=HTMLResponse)
        async def overlay_page() -> HTMLResponse:
            return HTMLResponse(
                content=(
                    files("context_live_translator")
                    .joinpath("static/overlay.html")
                    .read_text(encoding="utf-8")
                ),
                headers={"Cache-Control": "no-store, max-age=0"},
            )

        @self.app.get("/health")
        async def health() -> dict[str, Any]:
            return {
                "status": "ok",
                "service": "context-live-translator-overlay",
                "clients": self.client_count,
            }

        @self.app.websocket("/ws/overlay")
        async def websocket_endpoint(socket: WebSocket) -> None:
            await socket.accept()
            self._clients.add(socket)
            try:
                await socket.send_json(self.snapshot())
                while True:
                    await socket.receive_text()
            except WebSocketDisconnect:
                pass
            finally:
                self._clients.discard(socket)

    def start(self, timeout: float = 5.0) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._ensure_port_available()
        self._stop_requested.clear()
        self._error = None
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="context-live-translator-overlay",
        )
        self._thread.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._error:
                raise RuntimeError(f"OBS overlay 啟動失敗：{self._error}") from self._error
            if self._server and self._server.started:
                return
            if not self._thread.is_alive():
                break
            time.sleep(0.02)
        self.stop()
        raise RuntimeError(f"OBS overlay 無法在 {OVERLAY_HOST}:{self.port} 啟動")

    def _ensure_port_available(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind((OVERLAY_HOST, self.port))
            except OSError as exc:
                raise RuntimeError(
                    f"localhost:{self.port} 已被占用，請關閉舊程式或更換連接埠"
                ) from exc

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            config = uvicorn.Config(
                self.app,
                host=OVERLAY_HOST,
                port=self.port,
                log_level="warning",
                access_log=False,
            )
            self._server = uvicorn.Server(config)
            if self._stop_requested.is_set():
                self._server.should_exit = True
            loop.run_until_complete(self._server.serve())
        except BaseException as exc:
            self._error = exc
        finally:
            self._server = None
            self._loop = None
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    def stop(self) -> None:
        self._stop_requested.set()
        if self._server:
            self._server.should_exit = True
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(5)
        self._thread = None
        self._server = None
        self._loop = None

    def publish_segment(self, segment: dict[str, Any]) -> None:
        segment_id = str(segment.get("id", "")).strip()
        if not segment_id:
            raise ValueError("Overlay segment requires a stable id")
        with self._state_lock:
            previous = self._segments.get(segment_id)
            if previous and self._segment_is_stale(segment, previous):
                return
            before = set(self._segments)
            if segment_id != "__preview__":
                self._segments.pop("__preview__", None)
            self._sequence += 1
            stored = dict(segment)
            stored["update_sequence"] = self._sequence
            self._segments[segment_id] = stored
            self._trim_segments()
            ordered = self._ordered_segments()
            after = set(self._segments)
            event_type = self._segment_event_type(previous, stored)
            payload = {
                "type": "upsert",
                "event_type": event_type,
                "replace_id": segment_id,
                "segment": dict(stored),
                "removed_ids": sorted((before | {segment_id}) - after),
                "order": [item["id"] for item in ordered],
                "sequence": self._sequence,
            }
        self._broadcast(payload)

    def publish_preview(self) -> None:
        self.publish_segment(
            {
                "id": "__preview__",
                "started_at": 0,
                "source_language": "en",
                "source_text": "Context-aware live translation preview",
                "target_language": "繁中",
                "translation": "具備上下文回修的即時翻譯預覽",
                "status": "provisional",
                "revision": 0,
                "source_language_uncertain": False,
                "route_id": "preview",
                "route_label": "預覽",
                "context_group_id": "conversation",
            }
        )

    def clear(self) -> None:
        with self._state_lock:
            self._segments.clear()
            self._sequence += 1
            sequence = self._sequence
        self._broadcast({"type": "clear", "sequence": sequence})

    def update_settings(self, max_lines: int, style: dict[str, Any]) -> None:
        with self._state_lock:
            before = set(self._segments)
            self.max_lines = max(1, min(8, int(max_lines)))
            self._style = dict(style)
            self._trim_segments()
            after = set(self._segments)
            self._sequence += 1
            payload = self.snapshot()
            payload["removed_ids"] = sorted(before - after)
        self._broadcast(payload)

    def _ordered_segments(self) -> list[dict[str, Any]]:
        return sorted(
            self._segments.values(),
            key=lambda item: (float(item.get("started_at", 0)), str(item.get("id", ""))),
        )

    def _trim_segments(self) -> None:
        ordered = self._ordered_segments()
        for item in ordered[: max(0, len(ordered) - self.max_lines)]:
            self._segments.pop(str(item["id"]), None)

    @staticmethod
    def _segment_is_stale(
        incoming: dict[str, Any],
        current: dict[str, Any],
    ) -> bool:
        incoming_revision = int(incoming.get("revision", 0) or 0)
        current_revision = int(current.get("revision", 0) or 0)
        if incoming_revision != current_revision:
            return incoming_revision < current_revision
        incoming_updated = float(incoming.get("last_updated_at", 0) or 0)
        current_updated = float(current.get("last_updated_at", 0) or 0)
        return bool(incoming_updated and current_updated and incoming_updated < current_updated)

    @staticmethod
    def _segment_event_type(
        previous: dict[str, Any] | None,
        current: dict[str, Any],
    ) -> str:
        if previous is None:
            return "initial"
        if (
            current.get("translation") != previous.get("translation")
            or current.get("source_text") != previous.get("source_text")
            or int(current.get("revision", 0) or 0)
            > int(previous.get("revision", 0) or 0)
        ):
            return "revision"
        if current.get("status") != previous.get("status"):
            return "status"
        return "update"

    def _broadcast(self, payload: dict[str, Any]) -> None:
        loop = self._loop
        if not loop or not loop.is_running():
            return
        asyncio.run_coroutine_threadsafe(self._send_all(payload), loop)

    async def _send_all(self, payload: dict[str, Any]) -> None:
        message = json.dumps(payload, ensure_ascii=False)
        dead: list[WebSocket] = []
        for client in tuple(self._clients):
            try:
                await client.send_text(message)
            except Exception:
                dead.append(client)
        for client in dead:
            self._clients.discard(client)
