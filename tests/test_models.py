from context_live_translator.models import (
    AudioSource,
    LanguageSpec,
    SegmentStatus,
    TranscriptSegment,
    same_language,
)


def make_segment() -> TranscriptSegment:
    return TranscriptSegment(
        id="one",
        started_at=1.0,
        ended_at=2.0,
        source_language="ja",
        target_language=LanguageSpec("zh-TW", "繁中", "Taiwan wording"),
        raw_asr_text="原始",
        corrected_source_text="修正",
        translation="譯文",
        status=SegmentStatus.PROVISIONAL,
        revision=2,
    )


def test_audio_fingerprint_is_stable_and_kind_specific() -> None:
    first = AudioSource("input", "7", "USB Audio", "WASAPI", 2, 48000)
    same = AudioSource("input", "19", "USB Audio", "WASAPI", 2, 48000)
    loopback = AudioSource("loopback", "7", "USB Audio", "WASAPI", 2, 48000, True)
    assert first.fingerprint == same.fingerprint
    assert first.fingerprint != loopback.fingerprint
    assert "系統播放" in loopback.label


def test_same_language_uses_base_language() -> None:
    assert same_language("zh", "zh-TW")
    assert same_language("en-US", "en")
    assert not same_language("ja", "zh-TW")


def test_segment_snapshot_round_trip_preserves_enum_and_language() -> None:
    original = make_segment()
    restored = TranscriptSegment.from_snapshot(original.snapshot())
    assert restored == original
    assert restored.status is SegmentStatus.PROVISIONAL
    assert restored.target_language.code == "zh-TW"
    assert restored.source_text == "修正"
