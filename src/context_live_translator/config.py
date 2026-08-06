from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .models import (
    SOURCE_LANGUAGES,
    TARGET_LANGUAGES,
    AudioRouteConfig,
    LanguageSpec,
)

APP_NAME = "ContextLiveTranslator"
LOCAL_APPDATA = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
APP_DIR = LOCAL_APPDATA / APP_NAME
CONFIG_PATH = APP_DIR / "config.json"
SESSIONS_DIR = APP_DIR / "sessions"
MODELS_DIR = APP_DIR / "models"


@dataclass
class AppConfig:
    audio_source_fingerprint: str = ""
    source_language: str = "auto"
    target_language_code: str = "zh-TW"
    target_language_name: str = "繁體中文（台灣）"
    target_language_instruction: str = (
        "Use Taiwan Traditional Chinese characters, vocabulary, and natural spoken wording."
    )
    whisper_model_path: str = ""
    whisper_device: str = "auto"
    whisper_compute_type: str = "auto"
    llama_server_path: str = ""
    llama_model_path: str = ""
    llama_gpu_layers: int = 99
    llama_context: int = 4096
    llama_port: int = 8081
    input_gain_db: int = 0
    input_threshold: float = 0.008
    audio_routes: list[AudioRouteConfig] = field(
        default_factory=lambda: [AudioRouteConfig()]
    )
    silence_ms: int = 700
    max_utterance_seconds: int = 12
    max_no_speech_prob: float = 0.60
    min_avg_logprob: float = -1.0
    max_compression_ratio: float = 2.4
    normalize_zh_tw: bool = True
    auto_language_confidence: float = 0.60
    revision_window: int = 3
    finalization_seconds: int = 15
    obs_overlay_enabled: bool = False
    obs_overlay_port: int = 8765
    obs_overlay_max_lines: int = 3
    obs_overlay_show_source: bool = False
    obs_overlay_font_family: str = "Microsoft JhengHei"
    obs_overlay_translation_size: int = 44
    obs_overlay_source_size: int = 26
    obs_overlay_text_color: str = "#FFFFFF"
    obs_overlay_source_color: str = "#D1D5DB"
    obs_overlay_background: str = "rgba(0, 0, 0, 0.68)"
    obs_overlay_outline_color: str = "#000000"
    obs_overlay_outline_px: int = 2
    obs_overlay_position: str = "bottom"
    obs_overlay_text_align: str = "center"
    obs_overlay_width_percent: int = 90

    @property
    def target_language(self) -> LanguageSpec:
        built_in = TARGET_LANGUAGES.get(self.target_language_code)
        if built_in and self.target_language_name == built_in.display_name:
            return built_in
        return LanguageSpec(
            self.target_language_code.strip() or "custom",
            self.target_language_name.strip() or "Custom language",
            self.target_language_instruction.strip(),
        )


def load_config(path: Path = CONFIG_PATH) -> AppConfig:
    if not path.exists():
        return AppConfig()
    try:
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        known = AppConfig.__dataclass_fields__
        scalar_values = {
            key: value
            for key, value in raw.items()
            if key in known and key != "audio_routes"
        }
        config = AppConfig(**scalar_values)
        if "audio_routes" in raw:
            config.audio_routes = _parse_audio_routes(raw.get("audio_routes"))
        else:
            config.audio_routes = [
                AudioRouteConfig(
                    source_fingerprint=config.audio_source_fingerprint,
                    source_language=config.source_language,
                    gain_db=config.input_gain_db,
                    threshold=config.input_threshold,
                )
            ]
    except (OSError, ValueError, TypeError):
        return AppConfig()
    if config.source_language not in SOURCE_LANGUAGES:
        config.source_language = "auto"
    if config.whisper_device not in {"auto", "cuda", "cpu"}:
        config.whisper_device = "auto"
    config.audio_routes = normalize_audio_routes(config.audio_routes)
    config.revision_window = min(8, max(1, int(config.revision_window)))
    config.finalization_seconds = min(120, max(5, int(config.finalization_seconds)))
    config.obs_overlay_port = min(65535, max(1024, int(config.obs_overlay_port)))
    config.obs_overlay_max_lines = min(8, max(1, int(config.obs_overlay_max_lines)))
    config.obs_overlay_translation_size = min(
        120, max(16, int(config.obs_overlay_translation_size))
    )
    config.obs_overlay_source_size = min(96, max(12, int(config.obs_overlay_source_size)))
    config.obs_overlay_outline_px = min(8, max(0, int(config.obs_overlay_outline_px)))
    config.obs_overlay_width_percent = min(
        100, max(25, int(config.obs_overlay_width_percent))
    )
    if config.obs_overlay_position not in {"top", "center", "bottom"}:
        config.obs_overlay_position = "bottom"
    if config.obs_overlay_text_align not in {"left", "center", "right"}:
        config.obs_overlay_text_align = "center"
    return config


def _parse_audio_routes(value: Any) -> list[AudioRouteConfig]:
    if not isinstance(value, list):
        return []
    known = AudioRouteConfig.__dataclass_fields__
    routes: list[AudioRouteConfig] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            routes.append(
                AudioRouteConfig(
                    **{key: item_value for key, item_value in item.items() if key in known}
                )
            )
        except (TypeError, ValueError):
            continue
    return routes


def normalize_audio_routes(routes: list[AudioRouteConfig]) -> list[AudioRouteConfig]:
    normalized: list[AudioRouteConfig] = []
    used_ids: set[str] = set()
    for index, route in enumerate(routes):
        route_id = str(route.id).strip() or f"route-{index + 1}"
        base_id = route_id
        suffix = 2
        while route_id in used_ids:
            route_id = f"{base_id}-{suffix}"
            suffix += 1
        used_ids.add(route_id)
        language = route.source_language if route.source_language in SOURCE_LANGUAGES else "auto"
        try:
            gain_db = float(route.gain_db)
        except (TypeError, ValueError):
            gain_db = 0.0
        try:
            threshold = float(route.threshold)
        except (TypeError, ValueError):
            threshold = 0.008
        normalized.append(
            AudioRouteConfig(
                id=route_id,
                label=str(route.label).strip() or f"音訊來源 {index + 1}",
                source_fingerprint=str(route.source_fingerprint),
                source_language=language,
                gain_db=min(30.0, max(0.0, gain_db)),
                threshold=min(1.0, max(0.0, threshold)),
                enabled=bool(route.enabled),
                context_group_id=str(route.context_group_id).strip() or "conversation",
            )
        )
    return normalized or [AudioRouteConfig()]


def save_config(config: AppConfig, path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(asdict(config), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)
