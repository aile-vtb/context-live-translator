from types import SimpleNamespace

import numpy as np
import pytest

from context_live_translator import audio
from context_live_translator.audio import (
    FRAME_SAMPLES,
    AudioCaptureManager,
    AudioEngine,
    db_to_linear_gain,
    list_input_sources,
    list_loopback_sources,
    meter_value_to_threshold,
    mix_input_channels,
    threshold_to_meter_value,
)
from context_live_translator.models import AudioRouteConfig, AudioSource


def test_gain_and_threshold_round_trip() -> None:
    assert db_to_linear_gain(20) == pytest.approx(10.0)
    assert db_to_linear_gain(-10) == 1.0
    threshold = meter_value_to_threshold(240)
    assert threshold_to_meter_value(threshold) == 240


def test_channel_mix_selects_dominant_mic_but_mixes_program_audio() -> None:
    dominant = np.column_stack(
        (np.ones(100, dtype=np.float32), np.full(100, 0.01, dtype=np.float32))
    )
    assert np.allclose(mix_input_channels(dominant), 1.0)
    stereo = np.column_stack(
        (np.ones(100, dtype=np.float32), np.zeros(100, dtype=np.float32))
    )
    # The zero channel is clearly weaker, so the live microphone path stays intact.
    assert np.allclose(mix_input_channels(stereo), 1.0)
    balanced = np.column_stack(
        (np.ones(100, dtype=np.float32), np.full(100, 0.5, dtype=np.float32))
    )
    assert np.allclose(mix_input_channels(balanced), 0.75)


def test_list_input_sources_preserves_backend_index(monkeypatch) -> None:
    devices = [
        {
            "name": "Output only",
            "max_input_channels": 0,
            "default_samplerate": 48000.0,
            "hostapi": 0,
        },
        {
            "name": "RME Input",
            "max_input_channels": 2,
            "default_samplerate": 48000.0,
            "hostapi": 1,
        },
    ]
    monkeypatch.setattr(audio.sd, "query_devices", lambda: devices)
    monkeypatch.setattr(
        audio.sd,
        "query_hostapis",
        lambda: [{"name": "MME"}, {"name": "Windows WASAPI"}],
    )
    result = list_input_sources()
    assert len(result) == 1
    assert result[0].backend_id == "1"
    assert result[0].kind == "input"


def test_list_loopback_sources_filters_normal_microphones(monkeypatch) -> None:
    fake = SimpleNamespace(
        all_microphones=lambda include_loopback: [
            SimpleNamespace(id="mic", name="Mic", isloopback=False, channels=1),
            SimpleNamespace(id="speaker", name="Speakers", isloopback=True, channels=2),
        ]
    )
    monkeypatch.setattr(audio, "sc", fake)
    result = list_loopback_sources()
    assert [item.backend_id for item in result] == ["speaker"]
    assert result[0].is_loopback


def test_audio_engine_emits_vad_finalized_segment() -> None:
    levels = []
    segments = []
    engine = AudioEngine(
        levels.append,
        lambda data, start, end, context: segments.append((data, start, end, context)),
        pytest.fail,
        lambda: "ja",
        threshold=0.001,
        silence_ms=60,
    )
    decisions = iter([True, True, True, True, False, False])
    engine._vad = SimpleNamespace(is_speech=lambda pcm, rate: next(decisions))  # noqa: SLF001
    engine.set_active(True)
    frames = np.full(FRAME_SAMPLES * 6, 0.1, dtype=np.float32)
    engine._process_data(frames, 16000)  # noqa: SLF001
    assert levels
    assert len(segments) == 1
    assert segments[0][3] == "ja"
    assert segments[0][0].size == FRAME_SAMPLES * 6


def test_non_windows_com_initializer_is_noop(monkeypatch) -> None:
    monkeypatch.setattr(audio.os, "name", "posix")
    cleanup = audio.initialize_windows_com()
    assert cleanup() is None


def test_capture_manager_opens_independent_routes_and_tags_callbacks(monkeypatch) -> None:
    instances = []

    class FakeEngine:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.monitoring = False
            self.closed = False
            instances.append(self)

        def open(self, source):
            self.source = source
            self.monitoring = True

        def close(self):
            self.closed = True
            self.monitoring = False

        def set_active(self, active):
            self.active = active

        def set_gain_db(self, value):
            self.gain = value

        def set_threshold(self, value):
            self.threshold = value

    monkeypatch.setattr(audio, "AudioEngine", FakeEngine)
    segments = []
    manager = AudioCaptureManager(lambda *args: None, lambda *args: segments.append(args), pytest.fail)
    mic = AudioSource("input", "1", "ADAT 3+4", "ASIO", 2, 48000)
    discord = AudioSource("input", "2", "ADAT 5+6", "ASIO", 2, 48000)
    manager.open_route(AudioRouteConfig("self", "自己", source_language="zh"), mic)
    manager.open_route(AudioRouteConfig("friend", "朋友", source_language="en"), discord)

    instances[0].kwargs["on_segment"](np.ones(4), 1.0, 2.0, "zh")
    instances[1].kwargs["on_segment"](np.ones(4), 1.5, 2.5, "en")

    assert manager.monitoring_route_ids == ("self", "friend")
    assert [item[0] for item in segments] == ["self", "friend"]
    manager.close_route("friend")
    assert manager.monitoring_route_ids == ("self",)
    assert instances[1].closed


def test_capture_manager_rejects_same_device_on_two_routes(monkeypatch) -> None:
    class FakeEngine:
        monitoring = False

        def __init__(self, **kwargs):
            pass

        def open(self, source):
            self.monitoring = True

        def close(self):
            self.monitoring = False

    monkeypatch.setattr(audio, "AudioEngine", FakeEngine)
    manager = AudioCaptureManager(lambda *args: None, lambda *args: None, pytest.fail)
    source = AudioSource("input", "1", "Same", "WASAPI", 2, 48000)
    manager.open_route(AudioRouteConfig("one", "One"), source)
    with pytest.raises(ValueError, match="同一音訊來源"):
        manager.open_route(AudioRouteConfig("two", "Two"), source)
