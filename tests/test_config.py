import json

from context_live_translator.config import AppConfig, load_config, save_config


def test_load_config_filters_unknown_fields_and_invalid_source(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "source_language": "xx-invalid",
                "revision_window": 100,
                "finalization_seconds": 1,
                "unknown": "ignored",
            }
        ),
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.source_language == "auto"
    assert config.revision_window == 8
    assert config.finalization_seconds == 5
    assert not hasattr(config, "unknown")


def test_save_and_load_custom_target(tmp_path) -> None:
    path = tmp_path / "nested" / "config.json"
    config = AppConfig(
        target_language_code="pt-BR",
        target_language_name="Português do Brasil",
        target_language_instruction="Use Brazilian wording.",
    )
    save_config(config, path)
    loaded = load_config(path)
    assert loaded.target_language.code == "pt-BR"
    assert loaded.target_language.display_name == "Português do Brasil"
    assert not path.with_suffix(".tmp").exists()


def test_corrupt_config_returns_defaults(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{broken", encoding="utf-8")
    assert load_config(path) == AppConfig()


def test_overlay_config_values_are_clamped(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "obs_overlay_port": 1,
                "obs_overlay_max_lines": 99,
                "obs_overlay_translation_size": 500,
                "obs_overlay_source_size": 1,
                "obs_overlay_outline_px": 99,
                "obs_overlay_width_percent": 1,
                "obs_overlay_position": "sideways",
                "obs_overlay_text_align": "justify",
            }
        ),
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.obs_overlay_port == 1024
    assert config.obs_overlay_max_lines == 8
    assert config.obs_overlay_translation_size == 120
    assert config.obs_overlay_source_size == 12
    assert config.obs_overlay_outline_px == 8
    assert config.obs_overlay_width_percent == 25
    assert config.obs_overlay_position == "bottom"
    assert config.obs_overlay_text_align == "center"


def test_legacy_single_audio_fields_migrate_to_main_route(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "audio_source_fingerprint": "input||ADAT 3+4|ASIO|2|48000",
                "source_language": "zh",
                "input_gain_db": 6,
                "input_threshold": 0.01,
            }
        ),
        encoding="utf-8",
    )
    config = load_config(path)
    route = config.audio_routes[0]
    assert route.id == "main"
    assert route.source_fingerprint == config.audio_source_fingerprint
    assert route.source_language == "zh"
    assert route.gain_db == 6
    assert route.threshold == 0.01


def test_audio_routes_round_trip_and_normalize_duplicate_ids(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "audio_routes": [
                    {"id": "speaker", "label": "自己", "source_language": "zh"},
                    {"id": "speaker", "label": "朋友", "source_language": "en"},
                ]
            }
        ),
        encoding="utf-8",
    )
    config = load_config(path)
    assert [route.id for route in config.audio_routes] == ["speaker", "speaker-2"]
    save_config(config, path)
    assert len(load_config(path).audio_routes) == 2
