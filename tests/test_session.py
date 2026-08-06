import json
from datetime import datetime

from context_live_translator.models import (
    LanguageSpec,
    SegmentStatus,
    TranscriptSegment,
)
from context_live_translator.session import (
    SessionWriter,
    _srt_time,
    rebuild_segments,
    safe_language_filename,
)


def make_segment() -> TranscriptSegment:
    return TranscriptSegment(
        id="one",
        started_at=100.0,
        ended_at=101.25,
        source_language="en",
        target_language=LanguageSpec("zh-TW", "繁中"),
        raw_asr_text="raw",
        corrected_source_text="corrected",
        translation="翻譯",
        status=SegmentStatus.PROVISIONAL,
        last_updated_at=100.0,
    )


def test_srt_time() -> None:
    assert _srt_time(3661.234) == "01:01:01,234"


def test_session_event_log_and_latest_outputs(tmp_path) -> None:
    writer = SessionWriter("zh-TW", tmp_path, datetime(2026, 1, 2, 3, 4, 5))
    item = make_segment()
    writer.record("provisional", item)
    item.corrected_source_text = "final source"
    item.translation = "最終譯文"
    item.revision = 1
    item.status = SegmentStatus.FINAL
    writer.record("finalized", item)
    lines = writer.events_path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["event_type"] for line in lines] == [
        "provisional",
        "finalized",
    ]
    assert "final source" in (writer.directory / "source.srt").read_text(encoding="utf-8")
    assert "最終譯文" in (
        writer.directory / "target.zh-TW.srt"
    ).read_text(encoding="utf-8")
    assert not list(writer.directory.glob("*.tmp"))


def test_rebuild_uses_last_event_and_skips_malformed_line(tmp_path) -> None:
    writer = SessionWriter("zh-TW", tmp_path)
    item = make_segment()
    writer.record("first", item)
    item.translation = "更新"
    writer.record("second", item)
    with writer.events_path.open("a", encoding="utf-8") as handle:
        handle.write("{bad\n")
    rebuilt = rebuild_segments(writer.events_path)
    assert rebuilt["one"].translation == "更新"


def test_safe_language_filename() -> None:
    assert safe_language_filename("pt-BR") == "pt-BR"
    assert safe_language_filename("../中文") == "custom"


def test_sessions_started_in_same_second_get_unique_directories(tmp_path) -> None:
    moment = datetime(2026, 1, 2, 3, 4, 5)
    first = SessionWriter("en", tmp_path, moment)
    second = SessionWriter("en", tmp_path, moment)
    assert first.directory.name == "20260102-030405"
    assert second.directory.name == "20260102-030405-01"


def test_multi_route_session_writes_combined_and_per_route_outputs(tmp_path) -> None:
    writer = SessionWriter("zh-TW", tmp_path)
    first = make_segment()
    first.route_id = "self"
    first.route_label = "自己"
    second = TranscriptSegment.from_snapshot(first.snapshot())
    second.id = "two"
    second.started_at = 101.5
    second.ended_at = 102.0
    second.route_id = "friend"
    second.route_label = "朋友"
    second.corrected_source_text = "hello"
    second.translation = "你好"
    writer.record("provisional", first)
    writer.record("provisional", second)

    combined = (writer.directory / "target.zh-TW.srt").read_text(encoding="utf-8")
    assert "[自己]" in combined and "[朋友]" in combined
    assert (writer.directory / "target.zh-TW.self.srt").exists()
    assert (writer.directory / "target.zh-TW.friend.srt").exists()
    writer.record_system_event("audio_route_error", {"route_id": "friend"})
    last_event = json.loads(writer.events_path.read_text(encoding="utf-8").splitlines()[-1])
    assert last_event["event_type"] == "audio_route_error"
