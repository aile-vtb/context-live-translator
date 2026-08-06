from __future__ import annotations

import re
from functools import lru_cache

from opencc import OpenCC

from .config import AppConfig
from .models import Recognition

HALLUCINATIONS = {
    "thank you",
    "thanks for watching",
    "subscribe",
    "字幕由 amara.org 社群提供",
    "ご視聴ありがとうございました",
    "시청해 주셔서 감사합니다",
}


@lru_cache(maxsize=1)
def _taiwan_converter() -> OpenCC:
    return OpenCC("s2twp")


def normalize_taiwan_chinese(text: str) -> str:
    return _taiwan_converter().convert(text).strip()


def compact_key(text: str) -> str:
    return re.sub(r"[\W_]+", "", text, flags=re.UNICODE).lower()


def rejection_reason(
    recognition: Recognition,
    duration_seconds: float,
    config: AppConfig,
) -> str | None:
    text = recognition.text.strip()
    if not text:
        return "空白辨識"
    if recognition.no_speech_prob > config.max_no_speech_prob:
        return "無語音機率過高"
    if recognition.avg_logprob < config.min_avg_logprob:
        return "辨識信心過低"
    if recognition.compression_ratio > config.max_compression_ratio:
        return "文字重複率過高"
    if duration_seconds < 0.35:
        return "語音片段過短"
    key = compact_key(text)
    if any(compact_key(item) == key for item in HALLUCINATIONS):
        return "常見 Whisper 幻覺"
    return None

