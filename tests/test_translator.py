from types import SimpleNamespace

import httpx
import pytest

from context_live_translator.models import (
    LanguageSpec,
    RevisionRequest,
    TranscriptSegment,
)
from context_live_translator.translator import (
    ContextRevisionWorker,
    LlamaServer,
    StructuredLlamaClient,
    decode_json_content,
    model_profile,
    revision_schema,
    translation_schema,
    validate_revision,
    validate_translation,
)


def segment(segment_id: str = "a") -> TranscriptSegment:
    return TranscriptSegment(
        id=segment_id,
        started_at=1,
        ended_at=2,
        source_language="en",
        target_language=LanguageSpec("zh-TW", "繁體中文（台灣）", "Use Taiwan wording."),
        raw_asr_text="hello",
        corrected_source_text="hello",
        translation="你好",
    )


def test_model_profiles_cover_gemma_qwen_and_generic() -> None:
    assert model_profile("Gemma-3-4b.gguf") == "gemma"
    assert model_profile("Qwen3-4B.gguf") == "qwen"
    assert model_profile("mistral.gguf") == "generic"


def test_decode_json_accepts_markdown_fence() -> None:
    assert decode_json_content('```json\n{"translation":"你好"}\n```') == {
        "translation": "你好"
    }


def test_translation_validation_and_schema() -> None:
    assert validate_translation({"translation": " Hello "}) == "Hello"
    assert translation_schema()["required"] == ["translation"]
    with pytest.raises(ValueError, match="translation"):
        validate_translation({"text": "no"})


def test_revision_rejects_reordered_ids() -> None:
    payload = {
        "items": [
            {"id": "b", "corrected_source_text": "b", "translation": "乙"},
            {"id": "a", "corrected_source_text": "a", "translation": "甲"},
        ]
    }
    with pytest.raises(ValueError, match="ID"):
        validate_revision(payload, ("a", "b"))
    assert revision_schema(("a", "b"))["properties"]["items"]["minItems"] == 2


def test_gemma_uses_json_object(monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": '{"translation":"哈囉"}'}}]}

    def fake_post(url, json, timeout, trust_env):
        captured["payload"] = json
        assert trust_env is False
        return FakeResponse()

    monkeypatch.setattr("context_live_translator.translator.httpx.post", fake_post)
    server = LlamaServer("", "gemma-3.gguf")
    monkeypatch.setattr(server, "start", lambda: None)
    client = StructuredLlamaClient(server, lambda status: None)
    assert client.translate(segment()) == "哈囉"
    assert captured["payload"]["response_format"] == {"type": "json_object"}


def test_qwen_prefers_schema_and_falls_back_on_http_400(monkeypatch) -> None:
    calls = []

    class FakeResponse:
        def __init__(self, status_code):
            self.status_code = status_code
            self.request = httpx.Request("POST", "http://localhost")

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError(
                    "bad request",
                    request=self.request,
                    response=httpx.Response(self.status_code, request=self.request),
                )

        def json(self):
            return {"choices": [{"message": {"content": '{"translation":"你好"}'}}]}

    def fake_post(url, json, timeout, trust_env):
        calls.append(json["response_format"]["type"])
        assert trust_env is False
        return FakeResponse(400 if len(calls) == 1 else 200)

    statuses = []
    monkeypatch.setattr("context_live_translator.translator.httpx.post", fake_post)
    server = LlamaServer("", "qwen3.gguf")
    monkeypatch.setattr(server, "start", lambda: None)
    client = StructuredLlamaClient(server, statuses.append)
    assert client.translate(segment()) == "你好"
    assert calls == ["json_schema", "json_object"]
    assert "qwen" in statuses[0]


def test_context_revision_preserves_ids(monkeypatch) -> None:
    first, second = segment("a"), segment("b")
    response_payload = {
        "items": [
            {"id": "a", "corrected_source_text": "Hello", "translation": "你好"},
            {"id": "b", "corrected_source_text": "World", "translation": "世界"},
        ]
    }
    monkeypatch.setattr(
        "context_live_translator.translator.httpx.post",
        lambda url, json, timeout, trust_env: SimpleNamespace(
            status_code=200,
            raise_for_status=lambda: None,
            json=lambda: {
                "choices": [{"message": {"content": response_payload}}]
            },
        ),
    )
    server = LlamaServer("", "qwen.gguf")
    monkeypatch.setattr(server, "start", lambda: None)
    client = StructuredLlamaClient(server, lambda status: None)
    request = RevisionRequest(7, first.target_language, None, (first, second))
    result = client.revise(request)
    assert result.generation == 7
    assert [item.id for item in result.items] == ["a", "b"]


def test_revision_worker_queue_is_latest_wins() -> None:
    worker = ContextRevisionWorker(
        SimpleNamespace(revise=lambda request: None),
        lambda result: None,
        lambda generation, error: None,
    )
    first = RevisionRequest(1, segment().target_language, None, (segment("a"),))
    second = RevisionRequest(2, segment().target_language, None, (segment("b"),))
    worker.submit(first)
    worker.submit(second)
    assert worker._queue.get_nowait().generation == 2  # noqa: SLF001


def test_server_start_treats_local_health_timeout_as_not_running(monkeypatch, tmp_path) -> None:
    executable = tmp_path / "llama-server.exe"
    model = tmp_path / "model.gguf"
    executable.write_bytes(b"exe")
    model.write_bytes(b"model")
    process = SimpleNamespace(
        poll=lambda: None,
        terminate=lambda: None,
        wait=lambda timeout: None,
    )
    monkeypatch.setattr(
        "context_live_translator.translator.httpx.get",
        lambda url, timeout, trust_env: (_ for _ in ()).throw(
            httpx.ConnectTimeout("empty port")
        ),
    )
    monkeypatch.setattr(
        "context_live_translator.translator.subprocess.Popen",
        lambda *args, **kwargs: process,
    )
    times = iter([0.0, 2.0])
    monkeypatch.setattr(
        "context_live_translator.translator.time.monotonic",
        lambda: next(times),
    )
    server = LlamaServer(str(executable), str(model))
    with pytest.raises(TimeoutError):
        server.start(timeout=1)


def test_server_cannot_restart_after_session_stop() -> None:
    server = LlamaServer("missing.exe", "missing.gguf")
    server.stop()
    with pytest.raises(RuntimeError, match="session 結束後重新啟動"):
        server.start()
