from __future__ import annotations

import time
import uuid
from collections import OrderedDict
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal, Slot

from .audio import AudioCaptureManager
from .config import AppConfig, normalize_audio_routes
from .model_manager import validate_whisper_model
from .models import (
    SOURCE_LANGUAGES,
    AudioRouteConfig,
    AudioSource,
    Recognition,
    RevisionRequest,
    RevisionResult,
    SegmentStatus,
    TranscriptSegment,
    same_language,
)
from .overlay import OverlayServer, overlay_style, overlay_url, segment_payload
from .session import SessionWriter
from .speech import SpeechWorker
from .text_processing import normalize_taiwan_chinese, rejection_reason
from .translator import (
    ContextRevisionWorker,
    LlamaServer,
    StructuredLlamaClient,
    TranslationWorker,
)


def clone_segment(segment: TranscriptSegment) -> TranscriptSegment:
    return TranscriptSegment.from_snapshot(segment.snapshot())


class AppController(QObject):
    level_changed = Signal(float)
    route_level_changed = Signal(str, float)
    status_changed = Signal(str)
    error_occurred = Signal(str)
    segment_changed = Signal(object)
    segments_cleared = Signal()
    running_changed = Signal(bool)
    settings_locked_changed = Signal(bool)
    overlay_running_changed = Signal(bool)
    overlay_status_changed = Signal(str)

    _recognition_ready = Signal(str, object, float, float)
    _translation_ready = Signal(object)
    _revision_ready = Signal(object)
    _revision_error = Signal(int, str)
    _audio_error_ready = Signal(str, str)

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self.config.audio_routes = normalize_audio_routes(config.audio_routes)
        self.audio = AudioCaptureManager(
            on_level=self._on_audio_level,
            on_segment=self._on_audio_segment,
            on_error=self._audio_error_ready.emit,
            silence_ms=config.silence_ms,
            max_seconds=config.max_utterance_seconds,
        )
        self._speech: SpeechWorker | None = None
        self._translation: TranslationWorker | None = None
        self._revision: ContextRevisionWorker | None = None
        self._server: LlamaServer | None = None
        self._overlay: OverlayServer | None = None
        self._session: SessionWriter | None = None
        self._segments: OrderedDict[str, TranscriptSegment] = OrderedDict()
        self._running = False
        self._accept_results = False
        self._revision_generation = 0
        self._last_duplicates: dict[str, tuple[str, float]] = {}

        self._recognition_ready.connect(self._handle_recognition)
        self._translation_ready.connect(self._handle_initial_translation)
        self._revision_ready.connect(self._handle_revision)
        self._revision_error.connect(self._handle_revision_error)
        self._audio_error_ready.connect(self._on_audio_error)
        self.segment_changed.connect(self._publish_overlay_segment)
        self.segments_cleared.connect(self.clear_overlay)

        self._finalize_timer = QTimer(self)
        self._finalize_timer.setInterval(1000)
        self._finalize_timer.timeout.connect(self.finalize_expired)
        self._finalize_timer.start()

    @property
    def running(self) -> bool:
        return self._running

    @property
    def workers_started(self) -> bool:
        return self._speech is not None

    @property
    def segments(self) -> tuple[TranscriptSegment, ...]:
        return tuple(clone_segment(segment) for segment in self._segments.values())

    @property
    def obs_overlay_url(self) -> str:
        return overlay_url(self.config.obs_overlay_port)

    @property
    def overlay_running(self) -> bool:
        return bool(self._overlay and self._overlay.running)

    def configure_overlay(self) -> bool:
        if not self.config.obs_overlay_enabled:
            self.stop_overlay()
            self.overlay_status_changed.emit("OBS Overlay 已停用")
            return True
        if self.config.obs_overlay_port == self.config.llama_port:
            self.stop_overlay()
            self.overlay_status_changed.emit(
                "OBS Overlay port 不可與 llama.cpp port 相同"
            )
            return False
        if (
            self._overlay
            and self._overlay.running
            and self._overlay.port == self.config.obs_overlay_port
        ):
            self._overlay.update_settings(
                self.config.obs_overlay_max_lines,
                overlay_style(self.config),
            )
            self.overlay_status_changed.emit(f"運作中：{self.obs_overlay_url}")
            return True
        self.stop_overlay()
        server = OverlayServer(
            port=self.config.obs_overlay_port,
            max_lines=self.config.obs_overlay_max_lines,
            style=overlay_style(self.config),
        )
        try:
            server.start()
        except Exception as exc:
            server.stop()
            self._overlay = None
            self.overlay_running_changed.emit(False)
            self.overlay_status_changed.emit(str(exc))
            return False
        self._overlay = server
        for segment in self._segments.values():
            payload = segment_payload(segment)
            if payload:
                server.publish_segment(payload)
        self.overlay_running_changed.emit(True)
        self.overlay_status_changed.emit(f"運作中：{self.obs_overlay_url}")
        return True

    def stop_overlay(self) -> None:
        server, self._overlay = self._overlay, None
        if server:
            server.stop()
        self.overlay_running_changed.emit(False)

    def preview_overlay(self) -> None:
        if not self._overlay or not self._overlay.running:
            self.overlay_status_changed.emit("請先啟用並套用 OBS Overlay")
            return
        self._overlay.publish_preview()
        self.overlay_status_changed.emit("已送出預覽字幕")

    @Slot(object)
    def _publish_overlay_segment(self, value: object) -> None:
        if not isinstance(value, TranscriptSegment) or not self._overlay:
            return
        payload = segment_payload(value)
        if payload:
            self._overlay.publish_segment(payload)

    @Slot()
    def clear_overlay(self) -> None:
        if self._overlay:
            self._overlay.clear()

    def monitor_source(self, source: AudioSource) -> None:
        self.monitor_route(self.config.audio_routes[0].id, source)

    def monitor_route(self, route_id: str, source: AudioSource) -> None:
        if self.workers_started:
            self.error_occurred.emit("請先停止目前 session，再變更音訊來源")
            return
        route = self._route(route_id)
        if route is None:
            self.error_occurred.emit(f"找不到音訊 route：{route_id}")
            return
        try:
            self.audio.open_route(route, source)
            route.source_fingerprint = source.fingerprint
            if route is self.config.audio_routes[0]:
                self.config.audio_source_fingerprint = source.fingerprint
            self.status_changed.emit(f"正在監聽「{route.label}」：{source.name}")
        except Exception as exc:
            self.audio.close_route(route_id)
            self.error_occurred.emit(f"無法開啟「{route.label}」音訊來源：{exc}")

    def close_route(self, route_id: str) -> None:
        if self.workers_started:
            self.error_occurred.emit("請先停止目前 session，再變更音訊來源")
            return
        self.audio.close_route(route_id)

    def set_input_threshold(self, threshold: float) -> None:
        self.config.input_threshold = threshold
        self.set_route_threshold(self.config.audio_routes[0].id, threshold)

    def set_input_gain_db(self, gain_db: int) -> None:
        self.config.input_gain_db = gain_db
        self.set_route_gain_db(self.config.audio_routes[0].id, gain_db)

    def set_route_threshold(self, route_id: str, threshold: float) -> None:
        route = self._route(route_id)
        if route:
            route.threshold = threshold
        self.audio.set_route_threshold(route_id, threshold)

    def set_route_gain_db(self, route_id: str, gain_db: float) -> None:
        route = self._route(route_id)
        if route:
            route.gain_db = gain_db
        self.audio.set_route_gain_db(route_id, gain_db)

    def start(self) -> None:
        if self._running:
            return
        if self.workers_started:
            self.resume()
            return
        error = self._validate_start()
        if error:
            self.error_occurred.emit(error)
            return

        self._segments.clear()
        self.segments_cleared.emit()
        self._last_duplicates.clear()
        self._revision_generation = 0
        self._session = SessionWriter(self.config.target_language.code)
        self._server = LlamaServer(
            self.config.llama_server_path,
            self.config.llama_model_path,
            self.config.llama_gpu_layers,
            self.config.llama_context,
            self.config.llama_port,
        )
        client = StructuredLlamaClient(self._server, self.status_changed.emit)
        self._speech = SpeechWorker(
            self.config.whisper_model_path,
            self.config.whisper_device,
            self.config.whisper_compute_type,
            self._recognition_ready.emit,
            self.status_changed.emit,
            self.error_occurred.emit,
            cuda_library_paths=(self.config.llama_server_path,),
        )
        self._translation = TranslationWorker(
            client,
            self._translation_ready.emit,
            self.status_changed.emit,
        )
        self._revision = ContextRevisionWorker(
            client,
            self._revision_ready.emit,
            self._revision_error.emit,
        )
        self._accept_results = True
        self._speech.start()
        self._translation.start()
        self._revision.start()
        self.audio.set_active(True)
        self._running = True
        self.running_changed.emit(True)
        self.settings_locked_changed.emit(True)
        source_summary = "、".join(
            f"{route.label}={SOURCE_LANGUAGES[route.source_language].display_name}"
            for route in self.config.audio_routes
            if route.enabled
        )
        self.status_changed.emit(
            f"已開始聽讀；目標={self.config.target_language.display_name}；"
            f"來源：{source_summary}"
        )

    def _validate_start(self) -> str | None:
        if (
            self.config.obs_overlay_enabled
            and self.config.obs_overlay_port == self.config.llama_port
        ):
            return "OBS Overlay port 不可與 llama.cpp port 相同"
        enabled_routes = [route for route in self.config.audio_routes if route.enabled]
        if not enabled_routes:
            return "請至少啟用一個音訊來源"
        missing_routes = [
            route.label
            for route in enabled_routes
            if not self.audio.is_monitoring(route.id)
        ]
        if missing_routes:
            return "以下音訊來源尚未成功開啟：" + "、".join(missing_routes)
        if any(route.source_language not in SOURCE_LANGUAGES for route in enabled_routes):
            return "音訊來源的語言設定無效"
        model_validation = validate_whisper_model(self.config.whisper_model_path)
        if not model_validation.valid:
            return model_validation.message + "；請在模型設定頁偵測、下載或選取模型"
        if (
            not self.config.llama_server_path
            or not Path(self.config.llama_server_path).is_file()
        ):
            return "找不到 llama-server.exe；請查看 README 的模型準備章節"
        if (
            not self.config.llama_model_path
            or not Path(self.config.llama_model_path).is_file()
        ):
            return "找不到本機 GGUF 模型；請查看 README 的模型準備與授權章節"
        try:
            assert self.config.target_language.code.strip()
            assert self.config.target_language.display_name.strip()
        except AssertionError:
            return "目標語言代碼與名稱不能空白"
        return None

    def pause(self) -> None:
        if not self._running:
            return
        self.audio.set_active(False)
        self._running = False
        self.running_changed.emit(False)
        self.status_changed.emit("已暫停；模型與 session 保持開啟")

    def resume(self) -> None:
        if self.workers_started and self.audio.monitoring:
            self.audio.set_active(True)
            self._running = True
            self.running_changed.emit(True)
            self.status_changed.emit("已繼續聽讀")
            return
        self.start()

    def stop(self) -> None:
        if not self.workers_started and not self._running:
            return
        self.audio.set_active(False)
        self._running = False
        self._accept_results = False
        self._revision_generation += 1
        speech, self._speech = self._speech, None
        translation, self._translation = self._translation, None
        revision, self._revision = self._revision, None
        if speech:
            speech.stop()
        if self._server:
            self._server.stop()
        if translation:
            translation.stop()
        if revision:
            revision.stop()
        self._server = None
        self.finalize_all()
        self._session = None
        self.running_changed.emit(False)
        self.settings_locked_changed.emit(False)
        self.status_changed.emit("Session 已停止並寫出最新成稿")

    def shutdown(self) -> None:
        self.stop()
        self.stop_overlay()
        self.audio.close()

    def clear(self) -> None:
        if self.workers_started:
            self.error_occurred.emit("請先停止 session，再清除畫面")
            return
        self._segments.clear()
        self.segments_cleared.emit()
        self.status_changed.emit("已清除畫面；磁碟上的 session 記錄未刪除")

    def _on_audio_level(self, route_id: str, level: float) -> None:
        self.route_level_changed.emit(route_id, level)
        if route_id == self.config.audio_routes[0].id:
            self.level_changed.emit(level)

    def _on_audio_error(self, route_id: str, message: str) -> None:
        route = self._route(route_id)
        label = route.label if route else route_id
        self.audio.close_route(route_id)
        if self._session:
            self._session.record_system_event(
                "audio_route_error",
                {"route_id": route_id, "route_label": label, "message": message},
            )
        self.error_occurred.emit(
            f"「{label}」{message}。只停止這一路，不會切換到其他裝置。"
        )

    def _on_audio_segment(
        self,
        route_id: str,
        audio: np.ndarray,
        started_at: float,
        ended_at: float,
        language: str,
    ) -> None:
        if self._speech:
            route = self._route(route_id)
            requested_language = route.source_language if route else language
            self._speech.submit(
                route_id,
                audio,
                started_at,
                ended_at,
                requested_language,
            )

    @Slot(str, object, float, float)
    def _handle_recognition(
        self,
        route_id: str | Recognition,
        recognition: Recognition | float,
        started_at: float,
        ended_at: float | None = None,
    ) -> None:
        if isinstance(route_id, Recognition):
            ended_at = started_at
            started_at = float(recognition)
            recognition = route_id
            route_id = self.config.audio_routes[0].id
        assert isinstance(recognition, Recognition)
        assert ended_at is not None
        if not self._accept_results:
            return
        route = self._route(route_id)
        if route is None:
            return
        reason = rejection_reason(recognition, ended_at - started_at, self.config)
        if reason:
            self.status_changed.emit(f"已略過片段：{reason}")
            return
        raw_text = recognition.text.strip()
        normalized = (
            normalize_taiwan_chinese(raw_text)
            if recognition.language == "zh" and self.config.normalize_zh_tw
            else raw_text
        )
        now_monotonic = time.monotonic()
        duplicate_key = f"{recognition.language}:{normalized}"
        last_duplicate_key, last_duplicate_at = self._last_duplicates.get(
            route_id, ("", 0.0)
        )
        if (
            duplicate_key == last_duplicate_key
            and now_monotonic - last_duplicate_at < 8
        ):
            self.status_changed.emit(f"「{route.label}」已略過短時間內重複的辨識")
            return
        self._last_duplicates[route_id] = (duplicate_key, now_monotonic)
        now = time.time()
        segment = TranscriptSegment(
            id=uuid.uuid4().hex,
            started_at=started_at,
            ended_at=ended_at,
            source_language=recognition.language,
            target_language=self.config.target_language,
            raw_asr_text=raw_text,
            corrected_source_text=normalized,
            status=SegmentStatus.TRANSLATING,
            language_probability=recognition.language_probability,
            source_language_uncertain=(
                route.source_language == "auto"
                and recognition.language_probability < self.config.auto_language_confidence
            ),
            avg_logprob=recognition.avg_logprob,
            no_speech_prob=recognition.no_speech_prob,
            compression_ratio=recognition.compression_ratio,
            last_updated_at=now,
            route_id=route.id,
            route_label=route.label,
            context_group_id=route.context_group_id,
        )
        self._segments[segment.id] = segment
        self._record("recognized", segment)
        self.segment_changed.emit(clone_segment(segment))
        if same_language(segment.source_language, segment.target_language.code):
            segment.translation = (
                normalize_taiwan_chinese(segment.source_text)
                if segment.target_language.code == "zh-TW"
                else segment.source_text
            )
            self._make_provisional(segment)
        elif self._translation:
            self._translation.submit(segment)

    @Slot(object)
    def _handle_initial_translation(self, returned: TranscriptSegment) -> None:
        if not self._accept_results:
            return
        segment = self._segments.get(returned.id)
        if segment is None or segment.status == SegmentStatus.FINAL:
            return
        segment.translation = returned.translation
        segment.translation_latency_ms = returned.translation_latency_ms
        segment.error = returned.error
        if returned.error or not returned.translation:
            segment.status = SegmentStatus.ERROR
            segment.last_updated_at = time.time()
            self._record("translation_error", segment)
            self.segment_changed.emit(clone_segment(segment))
            self.status_changed.emit(returned.error or "翻譯失敗")
            return
        self._make_provisional(segment)

    def _make_provisional(self, segment: TranscriptSegment) -> None:
        segment.status = SegmentStatus.PROVISIONAL
        segment.last_updated_at = time.time()
        self._record("provisional", segment)
        self.segment_changed.emit(clone_segment(segment))
        self._finalize_by_count()
        self._schedule_revision()

    def _schedule_revision(self) -> None:
        if not self._revision:
            return
        mutable = [
            segment
            for segment in self._segments.values()
            if segment.status in {SegmentStatus.PROVISIONAL, SegmentStatus.REVISING}
            and segment.translation
        ][-self.config.revision_window :]
        if not mutable:
            return
        first_index = list(self._segments).index(mutable[0].id)
        locked_context = None
        for candidate in list(self._segments.values())[:first_index]:
            if candidate.status == SegmentStatus.FINAL:
                locked_context = candidate
        self._revision_generation += 1
        generation = self._revision_generation
        for segment in mutable:
            segment.status = SegmentStatus.REVISING
            segment.generation = generation
            self.segment_changed.emit(clone_segment(segment))
        request = RevisionRequest(
            generation=generation,
            target_language=self.config.target_language,
            locked_context=clone_segment(locked_context) if locked_context else None,
            mutable_segments=tuple(clone_segment(segment) for segment in mutable),
        )
        self._revision.submit(request)

    @Slot(object)
    def _handle_revision(self, result: RevisionResult) -> None:
        if not self._accept_results or result.generation != self._revision_generation:
            return
        for item in result.items:
            segment = self._segments.get(item.id)
            if (
                segment is None
                or segment.status == SegmentStatus.FINAL
                or segment.generation != result.generation
            ):
                continue
            changed = (
                item.corrected_source_text != segment.source_text
                or item.translation != segment.translation
            )
            segment.corrected_source_text = item.corrected_source_text
            segment.translation = item.translation
            segment.status = SegmentStatus.PROVISIONAL
            segment.error = None
            segment.last_updated_at = time.time()
            if changed:
                segment.revision += 1
                self._record("revised", segment)
            else:
                self._record("revision_checked", segment)
            self.segment_changed.emit(clone_segment(segment))
        self.status_changed.emit("上下文回修完成")
        self._finalize_by_count()

    @Slot(int, str)
    def _handle_revision_error(self, generation: int, message: str) -> None:
        if not self._accept_results or generation != self._revision_generation:
            return
        for segment in self._segments.values():
            if segment.status == SegmentStatus.REVISING and segment.generation == generation:
                segment.status = SegmentStatus.PROVISIONAL
                segment.error = message
                self._record("revision_error", segment)
                self.segment_changed.emit(clone_segment(segment))
        self.status_changed.emit(message + "；已保留初譯")

    @Slot()
    def finalize_expired(self, now: float | None = None) -> None:
        current = time.time() if now is None else now
        for segment in self._segments.values():
            if segment.status in {SegmentStatus.PROVISIONAL, SegmentStatus.REVISING} and (
                current - segment.last_updated_at >= self.config.finalization_seconds
            ):
                self._finalize_segment(segment)

    def _finalize_by_count(self) -> None:
        mutable = [
            segment
            for segment in self._segments.values()
            if segment.status in {SegmentStatus.PROVISIONAL, SegmentStatus.REVISING}
        ]
        while len(mutable) > self.config.revision_window:
            self._finalize_segment(mutable.pop(0))

    def finalize_all(self) -> None:
        for segment in self._segments.values():
            if segment.status != SegmentStatus.FINAL:
                self._finalize_segment(segment)

    def _finalize_segment(self, segment: TranscriptSegment) -> None:
        if segment.status == SegmentStatus.FINAL:
            return
        segment.status = SegmentStatus.FINAL
        segment.last_updated_at = time.time()
        self._record("finalized", segment)
        self.segment_changed.emit(clone_segment(segment))

    def _record(self, event_type: str, segment: TranscriptSegment) -> None:
        if self._session:
            self._session.record(event_type, segment)

    def _route(self, route_id: str) -> AudioRouteConfig | None:
        return next(
            (route for route in self.config.audio_routes if route.id == route_id),
            None,
        )
