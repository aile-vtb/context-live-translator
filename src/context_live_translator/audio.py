from __future__ import annotations

import ctypes
import os
import threading
import time
from collections.abc import Callable

import numpy as np
import sounddevice as sd
import webrtcvad
from scipy.signal import resample_poly

from .i18n import tr
from .models import AudioRouteConfig, AudioSource

try:
    import soundcard as sc
except (ImportError, OSError):  # SoundCard can fail to initialize outside Windows.
    sc = None  # type: ignore[assignment]

TARGET_RATE = 16_000
FRAME_MS = 30
FRAME_SAMPLES = TARGET_RATE * FRAME_MS // 1000
LEVEL_SCALE = 12.0
METER_MAX = 1000
MIN_GAIN_DB = 0.0
MAX_GAIN_DB = 30.0


def normalize_gain_db(gain_db: float) -> float:
    return min(MAX_GAIN_DB, max(MIN_GAIN_DB, float(gain_db)))


def db_to_linear_gain(gain_db: float) -> float:
    return 10.0 ** (normalize_gain_db(gain_db) / 20.0)


def rms_to_meter_value(rms: float) -> int:
    return round(min(1.0, max(0.0, rms) * LEVEL_SCALE) * METER_MAX)


def meter_value_to_threshold(value: int) -> float:
    return min(METER_MAX, max(0, int(value))) / METER_MAX / LEVEL_SCALE


def threshold_to_meter_value(threshold: float) -> int:
    return rms_to_meter_value(threshold)


def mix_input_channels(data: np.ndarray) -> np.ndarray:
    """Mix program audio, but preserve a clearly dominant raw microphone channel."""
    if data.ndim == 1:
        return data.astype(np.float32, copy=False)
    if data.shape[1] == 1:
        return data[:, 0].astype(np.float32, copy=False)
    channel_rms = np.sqrt(np.mean(np.square(data), axis=0))
    strongest = int(np.argmax(channel_rms))
    strongest_rms = float(channel_rms[strongest])
    other_rms = np.delete(channel_rms, strongest)
    if strongest_rms > 0 and (
        other_rms.size == 0 or float(np.max(other_rms)) < strongest_rms * 0.25
    ):
        return data[:, strongest].astype(np.float32, copy=False)
    return np.mean(data, axis=1, dtype=np.float32)


def list_input_sources() -> list[AudioSource]:
    devices = sd.query_devices()
    host_apis = sd.query_hostapis()
    sources: list[AudioSource] = []
    for index, raw in enumerate(devices):
        channels = int(raw["max_input_channels"])
        if channels <= 0:
            continue
        host_name = str(host_apis[int(raw["hostapi"])]["name"])
        sources.append(
            AudioSource(
                kind="input",
                backend_id=str(index),
                name=str(raw["name"]),
                host_api=host_name,
                channels=channels,
                sample_rate=int(round(float(raw["default_samplerate"]))),
            )
        )
    return sorted(sources, key=lambda item: (0 if "WASAPI" in item.host_api else 1, item.name))


def list_loopback_sources() -> list[AudioSource]:
    if sc is None:
        return []
    sources: list[AudioSource] = []
    for microphone in sc.all_microphones(include_loopback=True):
        if not bool(getattr(microphone, "isloopback", False)):
            continue
        channels_raw = getattr(microphone, "channels", 2)
        channels = channels_raw if isinstance(channels_raw, int) else len(channels_raw)
        sources.append(
            AudioSource(
                kind="loopback",
                backend_id=str(microphone.id),
                name=str(microphone.name),
                host_api="Windows WASAPI",
                channels=max(2, int(channels or 2)),
                sample_rate=48_000,
                is_loopback=True,
            )
        )
    return sorted(sources, key=lambda item: item.name)


def list_audio_sources() -> list[AudioSource]:
    return [*list_input_sources(), *list_loopback_sources()]


def initialize_windows_com() -> Callable[[], None]:
    """Initialize COM for a capture worker; SoundCard only initializes its import thread."""
    if os.name != "nt":
        return lambda: None
    ole32 = ctypes.OleDLL("ole32")
    ole32.CoInitializeEx.restype = ctypes.c_long
    result = int(ole32.CoInitializeEx(None, 0))
    unsigned_result = result & 0xFFFFFFFF
    if unsigned_result in {0x00000000, 0x00000001}:
        return lambda: ole32.CoUninitialize()
    if unsigned_result == 0x80010106:  # RPC_E_CHANGED_MODE: COM already initialized.
        return lambda: None
    raise OSError(f"CoInitializeEx failed with HRESULT 0x{unsigned_result:08X}")


class AudioEngine:
    """Capture one explicitly selected source and emit VAD-finalized utterances."""

    def __init__(
        self,
        on_level: Callable[[float], None],
        on_segment: Callable[[np.ndarray, float, float, str], None],
        on_error: Callable[[str], None],
        context_provider: Callable[[], str],
        gain_db: float = 0.0,
        threshold: float = 0.008,
        silence_ms: int = 700,
        max_seconds: int = 12,
    ) -> None:
        self.on_level = on_level
        self.on_segment = on_segment
        self.on_error = on_error
        self.context_provider = context_provider
        self.gain_db = normalize_gain_db(gain_db)
        self._gain_factor = db_to_linear_gain(self.gain_db)
        self.threshold = meter_value_to_threshold(threshold_to_meter_value(threshold))
        self.silence_frames = max(1, silence_ms // FRAME_MS)
        self.max_frames = max(1, max_seconds * 1000 // FRAME_MS)
        self._input_stream: sd.InputStream | None = None
        self._loopback_thread: threading.Thread | None = None
        self._loopback_stop = threading.Event()
        self._selected_source: AudioSource | None = None
        self._active = False
        self._vad = webrtcvad.Vad(2)
        self._pending = np.empty(0, dtype=np.float32)
        self._speech: list[np.ndarray] = []
        self._trailing = 0
        self._started_at = 0.0
        self._segment_context = "auto"
        self._lock = threading.RLock()
        self._error_reported = False

    @property
    def monitoring(self) -> bool:
        return self._input_stream is not None or (
            self._loopback_thread is not None and self._loopback_thread.is_alive()
        )

    @property
    def selected_source(self) -> AudioSource | None:
        return self._selected_source

    def open(self, source: AudioSource) -> None:
        self.close()
        self._error_reported = False
        if source.kind == "input":
            self._open_input(source)
        elif source.kind == "loopback":
            self._open_loopback(source)
        else:
            raise ValueError(f"Unsupported audio source kind: {source.kind}")
        self._selected_source = source

    def _open_input(self, source: AudioSource) -> None:
        device_index = int(source.backend_id)
        sd.check_input_settings(
            device=device_index,
            channels=source.channels,
            samplerate=source.sample_rate,
            dtype="float32",
        )
        self._input_stream = sd.InputStream(
            device=device_index,
            channels=source.channels,
            samplerate=source.sample_rate,
            dtype="float32",
            blocksize=0,
            callback=lambda data, frames, timing, status: self._sounddevice_callback(
                data, status, source.sample_rate
            ),
        )
        self._input_stream.start()

    def _open_loopback(self, source: AudioSource) -> None:
        if sc is None:
            raise RuntimeError(tr("SoundCard 無法載入，不能使用系統播放擷取"))
        self._loopback_stop.clear()
        self._loopback_thread = threading.Thread(
            target=self._loopback_run,
            args=(source,),
            daemon=True,
            name="wasapi-loopback",
        )
        self._loopback_thread.start()
        # Give the backend a short opportunity to report an invalid endpoint.
        time.sleep(0.05)
        if not self._loopback_thread.is_alive():
            raise RuntimeError(tr("無法開啟選定的 Windows 播放裝置"))

    def _loopback_run(self, source: AudioSource) -> None:
        def noop() -> None:
            return None

        uninitialize_com: Callable[[], None] = noop
        try:
            uninitialize_com = initialize_windows_com()
            assert sc is not None
            microphone = sc.get_microphone(source.backend_id, include_loopback=True)
            if not bool(getattr(microphone, "isloopback", False)):
                raise RuntimeError(tr("選定端點不是 WASAPI loopback 裝置"))
            with microphone.recorder(
                samplerate=source.sample_rate,
                blocksize=1024,
            ) as recorder:
                while not self._loopback_stop.is_set():
                    data = recorder.record(numframes=1024)
                    self._process_data(np.asarray(data), source.sample_rate)
        except Exception as exc:
            if not self._loopback_stop.is_set():
                self._report_error(tr("系統播放擷取中斷：{error}", error=exc))
        finally:
            uninitialize_com()

    def set_active(self, active: bool) -> None:
        with self._lock:
            self._active = active
            if not active:
                self._reset_segment()

    def set_threshold(self, threshold: float) -> None:
        normalized = meter_value_to_threshold(threshold_to_meter_value(threshold))
        with self._lock:
            self.threshold = normalized

    def set_gain_db(self, gain_db: float) -> None:
        normalized = normalize_gain_db(gain_db)
        with self._lock:
            self.gain_db = normalized
            self._gain_factor = db_to_linear_gain(normalized)

    def close(self) -> None:
        stream, self._input_stream = self._input_stream, None
        if stream:
            try:
                stream.stop()
                stream.close()
            except sd.PortAudioError:
                pass
        self._loopback_stop.set()
        thread, self._loopback_thread = self._loopback_thread, None
        if thread and thread is not threading.current_thread():
            thread.join(2)
        with self._lock:
            self._active = False
            self._selected_source = None
            self._reset_segment()

    def _sounddevice_callback(
        self,
        data: np.ndarray,
        status: sd.CallbackFlags,
        sample_rate: int,
    ) -> None:
        if status:
            self._report_error(tr("音訊裝置回報錯誤：{status}", status=status))
            return
        self._process_data(data, sample_rate)

    def _process_data(self, data: np.ndarray, sample_rate: int) -> None:
        mono = mix_input_channels(data)
        with self._lock:
            gain_factor = self._gain_factor
        mono = np.clip(mono * gain_factor, -1.0, 1.0).astype(np.float32, copy=False)
        rms = float(np.sqrt(np.mean(np.square(mono)))) if mono.size else 0.0
        self.on_level(min(1.0, rms * LEVEL_SCALE))
        with self._lock:
            if not self._active:
                return
            if sample_rate != TARGET_RATE:
                mono = resample_poly(mono, TARGET_RATE, sample_rate).astype(np.float32)
            self._pending = np.concatenate((self._pending, mono))
            self._consume_frames()

    def _consume_frames(self) -> None:
        while self._pending.size >= FRAME_SAMPLES:
            frame = self._pending[:FRAME_SAMPLES]
            self._pending = self._pending[FRAME_SAMPLES:]
            pcm = np.clip(frame * 32767, -32768, 32767).astype("<i2").tobytes()
            rms = float(np.sqrt(np.mean(np.square(frame))))
            is_speech = rms >= self.threshold and self._vad.is_speech(pcm, TARGET_RATE)
            if is_speech:
                if not self._speech:
                    self._started_at = time.time()
                    self._segment_context = self.context_provider()
                self._speech.append(frame.copy())
                self._trailing = 0
            elif self._speech:
                self._speech.append(frame.copy())
                self._trailing += 1
            if self._speech and (
                self._trailing >= self.silence_frames or len(self._speech) >= self.max_frames
            ):
                self._finalize()

    def _finalize(self) -> None:
        audio = np.concatenate(self._speech)
        ended_at = time.time()
        started_at = self._started_at
        segment_context = self._segment_context
        voiced_frames = len(self._speech) - self._trailing
        self._reset_segment()
        if voiced_frames >= 4:
            self.on_segment(audio, started_at, ended_at, segment_context)

    def _reset_segment(self) -> None:
        self._pending = np.empty(0, dtype=np.float32)
        self._speech = []
        self._trailing = 0
        self._started_at = 0.0
        self._segment_context = "auto"

    def _report_error(self, message: str) -> None:
        with self._lock:
            if self._error_reported:
                return
            self._error_reported = True
            self._active = False
            self._reset_segment()
        self.on_error(message)


class AudioCaptureManager:
    """Own multiple independent audio capture/VAD routes."""

    def __init__(
        self,
        on_level: Callable[[str, float], None],
        on_segment: Callable[[str, np.ndarray, float, float, str], None],
        on_error: Callable[[str, str], None],
        silence_ms: int = 700,
        max_seconds: int = 12,
    ) -> None:
        self.on_level = on_level
        self.on_segment = on_segment
        self.on_error = on_error
        self.silence_ms = silence_ms
        self.max_seconds = max_seconds
        self._engines: dict[str, AudioEngine] = {}
        self._sources: dict[str, AudioSource] = {}
        self._routes: dict[str, AudioRouteConfig] = {}
        self._lock = threading.RLock()

    @property
    def route_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._engines)

    @property
    def monitoring_route_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(
                route_id
                for route_id, engine in self._engines.items()
                if engine.monitoring
            )

    @property
    def monitoring(self) -> bool:
        return bool(self.monitoring_route_ids) or getattr(self, "_input_stream", None) is not None

    def is_monitoring(self, route_id: str) -> bool:
        with self._lock:
            engine = self._engines.get(route_id)
            legacy_monitoring = (
                route_id == "main" and getattr(self, "_input_stream", None) is not None
            )
            return bool(engine and engine.monitoring) or legacy_monitoring

    def selected_source(self, route_id: str) -> AudioSource | None:
        with self._lock:
            return self._sources.get(route_id)

    def open_route(self, route: AudioRouteConfig, source: AudioSource) -> None:
        self.close_route(route.id)
        with self._lock:
            duplicate = next(
                (
                    other_id
                    for other_id, other_source in self._sources.items()
                    if other_source.fingerprint == source.fingerprint and other_id != route.id
                ),
                None,
            )
        if duplicate:
            raise ValueError(
                tr("同一音訊來源已由 route「{route}」監聽", route=duplicate)
            )
        engine = AudioEngine(
            on_level=lambda level, route_id=route.id: self.on_level(route_id, level),
            on_segment=lambda audio, started, ended, language, route_id=route.id: (
                self.on_segment(route_id, audio, started, ended, language)
            ),
            on_error=lambda message, route_id=route.id: self.on_error(route_id, message),
            context_provider=lambda: route.source_language,
            gain_db=route.gain_db,
            threshold=route.threshold,
            silence_ms=self.silence_ms,
            max_seconds=self.max_seconds,
        )
        try:
            engine.open(source)
        except Exception:
            engine.close()
            raise
        with self._lock:
            self._engines[route.id] = engine
            self._sources[route.id] = source
            self._routes[route.id] = route

    def close_route(self, route_id: str) -> None:
        with self._lock:
            engine = self._engines.pop(route_id, None)
            self._sources.pop(route_id, None)
            self._routes.pop(route_id, None)
        if engine:
            engine.close()

    def set_active(self, active: bool) -> None:
        with self._lock:
            engines = tuple(
                (engine, self._routes[route_id].enabled)
                for route_id, engine in self._engines.items()
            )
        for engine, enabled in engines:
            engine.set_active(active and enabled)

    def set_route_gain_db(self, route_id: str, gain_db: float) -> None:
        with self._lock:
            engine = self._engines.get(route_id)
        if engine:
            engine.set_gain_db(gain_db)

    def set_route_threshold(self, route_id: str, threshold: float) -> None:
        with self._lock:
            engine = self._engines.get(route_id)
        if engine:
            engine.set_threshold(threshold)

    def close(self) -> None:
        with self._lock:
            route_ids = tuple(self._engines)
        for route_id in route_ids:
            self.close_route(route_id)
