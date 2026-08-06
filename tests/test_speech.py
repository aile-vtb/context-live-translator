from types import SimpleNamespace

import numpy as np

from context_live_translator.speech import SpeechWorker, resolve_compute, whisper_language_code


def test_auto_language_passes_none_to_whisper() -> None:
    assert whisper_language_code(object(), "auto") is None


def test_cantonese_uses_native_token_when_available() -> None:
    tokenizer = SimpleNamespace(token_to_id=lambda token: 42 if token == "<|yue|>" else None)
    model = SimpleNamespace(hf_tokenizer=tokenizer)
    assert whisper_language_code(model, "yue") == "yue"


def test_cantonese_falls_back_to_chinese_token() -> None:
    tokenizer = SimpleNamespace(token_to_id=lambda token: None)
    model = SimpleNamespace(hf_tokenizer=tokenizer)
    assert whisper_language_code(model, "yue") == "zh"


def test_explicit_cpu_auto_compute_uses_int8() -> None:
    assert resolve_compute("cpu", "auto") == ("cpu", "int8")
    assert resolve_compute("cuda", "auto") == ("cuda", "int8_float16")
    assert resolve_compute("cpu", "float32") == ("cpu", "float32")


def test_shared_speech_queue_preserves_audio_route_identity() -> None:
    worker = SpeechWorker("model", "cpu", "int8", lambda *args: None, lambda *args: None, lambda *args: None)
    worker.submit("discord", np.ones(10, dtype=np.float32), 1.0, 2.0, "en")
    scheduled_route = worker._queue.get_nowait()  # noqa: SLF001
    item = worker._route_queues["discord"][0]  # noqa: SLF001
    assert scheduled_route == "discord"
    assert item[3] == "en"


def test_shared_speech_queue_limits_each_route_independently() -> None:
    errors = []
    worker = SpeechWorker(
        "model",
        "cpu",
        "int8",
        lambda *args: None,
        lambda *args: None,
        errors.append,
    )
    audio = np.ones(10, dtype=np.float32)
    for index in range(5):
        worker.submit("noisy", audio, index, index + 1, "en")
    worker.submit("friend", audio, 10, 11, "ja")
    assert len(worker._route_queues["noisy"]) == 4  # noqa: SLF001
    assert len(worker._route_queues["friend"]) == 1  # noqa: SLF001
    assert "noisy" in errors[0]
