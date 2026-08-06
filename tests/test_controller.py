import time
from types import SimpleNamespace

import numpy as np

from context_live_translator.config import AppConfig
from context_live_translator.controller import AppController
from context_live_translator.models import (
    AudioRouteConfig,
    LanguageSpec,
    Recognition,
    RevisionItem,
    RevisionResult,
    SegmentStatus,
    TranscriptSegment,
)


def recognition(text: str = "hello") -> Recognition:
    return Recognition(text, "en", 0.9, -0.1, 0.05, 1.1)


def test_initial_translation_is_emitted_then_scheduled_for_revision(qcore_app) -> None:
    controller = AppController(AppConfig(source_language="en", target_language_code="zh-TW"))
    submitted = []
    revisions = []
    controller._translation = SimpleNamespace(submit=submitted.append)  # noqa: SLF001
    controller._revision = SimpleNamespace(submit=revisions.append)  # noqa: SLF001
    controller._accept_results = True  # noqa: SLF001
    events = []
    controller.segment_changed.connect(events.append)
    controller._handle_recognition(recognition(), 10.0, 11.0)  # noqa: SLF001
    assert len(submitted) == 1
    returned = submitted[0]
    returned.translation = "你好"
    controller._handle_initial_translation(returned)  # noqa: SLF001
    assert events[0].status == SegmentStatus.TRANSLATING
    assert any(item.translation == "你好" for item in events)
    assert revisions[0].mutable_segments[0].id == returned.id


def test_stale_revision_cannot_overwrite_newer_generation(qcore_app) -> None:
    controller = AppController(AppConfig())
    item = TranscriptSegment(
        "a",
        1,
        2,
        "en",
        LanguageSpec("zh-TW", "繁中"),
        "hello",
        "hello",
        "初譯",
        status=SegmentStatus.REVISING,
        generation=2,
        last_updated_at=time.time(),
    )
    controller._segments[item.id] = item  # noqa: SLF001
    controller._accept_results = True  # noqa: SLF001
    controller._revision_generation = 2  # noqa: SLF001
    stale = RevisionResult(1, (RevisionItem("a", "wrong", "錯"),))
    controller._handle_revision(stale)  # noqa: SLF001
    assert controller._segments["a"].translation == "初譯"  # noqa: SLF001


def test_revision_updates_same_segment_and_increments_revision(qcore_app) -> None:
    controller = AppController(AppConfig())
    item = TranscriptSegment(
        "a",
        1,
        2,
        "en",
        LanguageSpec("zh-TW", "繁中"),
        "hallo",
        "hallo",
        "哈囉",
        status=SegmentStatus.REVISING,
        generation=3,
        last_updated_at=time.time(),
    )
    controller._segments[item.id] = item  # noqa: SLF001
    controller._accept_results = True  # noqa: SLF001
    controller._revision_generation = 3  # noqa: SLF001
    controller._handle_revision(  # noqa: SLF001
        RevisionResult(3, (RevisionItem("a", "hello", "你好"),))
    )
    updated = controller._segments["a"]  # noqa: SLF001
    assert updated.corrected_source_text == "hello"
    assert updated.translation == "你好"
    assert updated.revision == 1
    assert updated.status == SegmentStatus.PROVISIONAL


def test_fourth_mutable_segment_locks_oldest(qcore_app) -> None:
    config = AppConfig(revision_window=3)
    controller = AppController(config)
    for number in range(4):
        item = TranscriptSegment(
            str(number),
            number,
            number + 0.5,
            "en",
            LanguageSpec("zh-TW", "繁中"),
            str(number),
            str(number),
            str(number),
            status=SegmentStatus.PROVISIONAL,
            last_updated_at=time.time(),
        )
        controller._segments[item.id] = item  # noqa: SLF001
    controller._finalize_by_count()  # noqa: SLF001
    assert controller._segments["0"].status == SegmentStatus.FINAL  # noqa: SLF001
    assert controller._segments["1"].status == SegmentStatus.PROVISIONAL  # noqa: SLF001


def test_idle_timeout_locks_segment(qcore_app) -> None:
    controller = AppController(AppConfig(finalization_seconds=15))
    item = TranscriptSegment(
        "a",
        1,
        2,
        "en",
        LanguageSpec("zh-TW", "繁中"),
        "hello",
        "hello",
        "你好",
        status=SegmentStatus.PROVISIONAL,
        last_updated_at=100,
    )
    controller._segments[item.id] = item  # noqa: SLF001
    controller.finalize_expired(116)
    assert item.status == SegmentStatus.FINAL


def test_same_language_skips_initial_translation(qcore_app) -> None:
    config = AppConfig(
        source_language="en",
        target_language_code="en",
        target_language_name="English",
        target_language_instruction="",
    )
    controller = AppController(config)
    initial = []
    revisions = []
    controller._translation = SimpleNamespace(submit=initial.append)  # noqa: SLF001
    controller._revision = SimpleNamespace(submit=revisions.append)  # noqa: SLF001
    controller._accept_results = True  # noqa: SLF001
    controller._handle_recognition(recognition(), 1, 2)  # noqa: SLF001
    assert not initial
    item = next(iter(controller._segments.values()))  # noqa: SLF001
    assert item.translation == "hello"
    assert revisions


def test_start_validation_rejects_empty_model_paths_even_in_existing_directory(
    qcore_app,
) -> None:
    controller = AppController(AppConfig())
    controller.audio._input_stream = SimpleNamespace()  # noqa: SLF001
    error = controller._validate_start()  # noqa: SLF001
    assert error is not None
    assert "Whisper" in error
    controller.audio._input_stream = None  # noqa: SLF001


def test_start_validation_rejects_overlay_llama_port_collision(qcore_app) -> None:
    controller = AppController(
        AppConfig(obs_overlay_enabled=True, obs_overlay_port=8081, llama_port=8081)
    )
    controller.audio._input_stream = SimpleNamespace()  # noqa: SLF001
    error = controller._validate_start()  # noqa: SLF001
    assert error is not None
    assert "port" in error
    controller.audio._input_stream = None  # noqa: SLF001


def test_segment_signal_publishes_overlay_revision_with_same_id(qcore_app) -> None:
    published = []
    fake_overlay = SimpleNamespace(publish_segment=published.append)
    controller = AppController(AppConfig())
    controller._overlay = fake_overlay  # type: ignore[assignment]  # noqa: SLF001
    item = TranscriptSegment(
        "stable-id",
        1,
        2,
        "en",
        LanguageSpec("zh-TW", "繁中"),
        "hello",
        "hello",
        "你好",
        status=SegmentStatus.PROVISIONAL,
    )
    controller.segment_changed.emit(item)
    item.translation = "您好"
    item.revision = 1
    controller.segment_changed.emit(item)
    assert [entry["id"] for entry in published] == ["stable-id", "stable-id"]
    assert published[-1]["translation"] == "您好"
    controller._overlay = None  # noqa: SLF001


def test_audio_segment_uses_current_route_language_after_restart(qcore_app) -> None:
    config = AppConfig(
        audio_routes=[AudioRouteConfig(id="main", source_language="ja")]
    )
    controller = AppController(config)
    submitted = []
    controller._speech = SimpleNamespace(submit=lambda *args: submitted.append(args))  # noqa: SLF001

    controller._on_audio_segment(  # noqa: SLF001
        "main", np.ones(10, dtype=np.float32), 1.0, 2.0, "en"
    )

    assert submitted[0][0] == "main"
    assert submitted[0][-1] == "ja"
