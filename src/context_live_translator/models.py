from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


@dataclass(frozen=True)
class LanguageSpec:
    code: str
    display_name: str
    instruction: str = ""


SOURCE_LANGUAGES: dict[str, LanguageSpec] = {
    "auto": LanguageSpec("auto", "自動偵測"),
    "zh": LanguageSpec("zh", "中文"),
    "yue": LanguageSpec("yue", "粵語"),
    "en": LanguageSpec("en", "English"),
    "ja": LanguageSpec("ja", "日本語"),
    "ko": LanguageSpec("ko", "한국어"),
}

TARGET_LANGUAGES: dict[str, LanguageSpec] = {
    "zh-TW": LanguageSpec(
        "zh-TW",
        "繁體中文（台灣）",
        "Use Taiwan Traditional Chinese characters, vocabulary, and natural spoken wording.",
    ),
    "zh-CN": LanguageSpec("zh-CN", "简体中文", "Use Simplified Chinese."),
    "en": LanguageSpec("en", "English"),
    "ja": LanguageSpec("ja", "日本語"),
    "ko": LanguageSpec("ko", "한국어"),
    "fr": LanguageSpec("fr", "Français"),
    "de": LanguageSpec("de", "Deutsch"),
    "es": LanguageSpec("es", "Español"),
}


def same_language(source_code: str, target_code: str) -> bool:
    source_base = source_code.lower().split("-", 1)[0]
    target_base = target_code.lower().split("-", 1)[0]
    return source_base == target_base


@dataclass(frozen=True)
class AudioSource:
    kind: str
    backend_id: str
    name: str
    host_api: str
    channels: int
    sample_rate: int
    is_loopback: bool = False

    @property
    def fingerprint(self) -> str:
        # PortAudio input indices can change after hot-plugging, while a WASAPI
        # loopback endpoint ID is a stable device GUID and should be retained.
        stable_backend_id = self.backend_id if self.is_loopback else ""
        return (
            f"{self.kind}|{stable_backend_id}|{self.name}|{self.host_api}|"
            f"{self.channels}|{self.sample_rate}"
        )

    @property
    def label(self) -> str:
        suffix = "系統播放" if self.is_loopback else self.host_api
        return f"{self.name} — {suffix}, {self.channels} ch, {self.sample_rate} Hz"


@dataclass
class AudioRouteConfig:
    id: str = "main"
    label: str = "主要音訊"
    source_fingerprint: str = ""
    source_language: str = "auto"
    gain_db: float = 0.0
    threshold: float = 0.008
    enabled: bool = True
    context_group_id: str = "conversation"


@dataclass(frozen=True)
class Recognition:
    text: str
    language: str
    language_probability: float
    avg_logprob: float
    no_speech_prob: float
    compression_ratio: float


class SegmentStatus(str, Enum):
    RECOGNIZED = "recognized"
    TRANSLATING = "translating"
    PROVISIONAL = "provisional"
    REVISING = "revising"
    FINAL = "final"
    ERROR = "error"


@dataclass
class TranscriptSegment:
    id: str
    started_at: float
    ended_at: float
    source_language: str
    target_language: LanguageSpec
    raw_asr_text: str
    corrected_source_text: str = ""
    translation: str = ""
    status: SegmentStatus = SegmentStatus.RECOGNIZED
    revision: int = 0
    generation: int = 0
    language_probability: float = 1.0
    source_language_uncertain: bool = False
    avg_logprob: float | None = None
    no_speech_prob: float | None = None
    compression_ratio: float | None = None
    translation_latency_ms: int | None = None
    error: str | None = None
    last_updated_at: float = 0.0
    route_id: str = "main"
    route_label: str = "主要音訊"
    context_group_id: str = "conversation"

    @property
    def source_text(self) -> str:
        return self.corrected_source_text or self.raw_asr_text

    def snapshot(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_snapshot(cls, data: dict[str, Any]) -> TranscriptSegment:
        values = dict(data)
        values["target_language"] = LanguageSpec(**values["target_language"])
        values["status"] = SegmentStatus(values["status"])
        return cls(**values)


@dataclass(frozen=True)
class RevisionItem:
    id: str
    corrected_source_text: str
    translation: str


@dataclass(frozen=True)
class RevisionRequest:
    generation: int
    target_language: LanguageSpec
    locked_context: TranscriptSegment | None
    mutable_segments: tuple[TranscriptSegment, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RevisionResult:
    generation: int
    items: tuple[RevisionItem, ...]
