from context_live_translator.config import AppConfig
from context_live_translator.main_window import MainWindow
from context_live_translator.models import (
    AudioRouteConfig,
    LanguageSpec,
    SegmentStatus,
    TranscriptSegment,
)


def test_gui_has_standalone_translation_tabs(monkeypatch, qcore_app) -> None:
    monkeypatch.setattr("context_live_translator.main_window.list_audio_sources", lambda: [])
    window = MainWindow(AppConfig())
    assert [window.tabs.tabText(index) for index in range(window.tabs.count())] == [
        "即時翻譯",
        "模型與進階",
        "OBS Overlay",
        "診斷",
    ]
    assert window.timeline.objectName() == "timeline"
    assert window.target_combo.findData("__custom__") >= 0
    assert not window.windowIcon().isNull()
    window.controller.shutdown()
    window.deleteLater()


def test_gui_has_obs_browser_source_controls(monkeypatch, qcore_app) -> None:
    monkeypatch.setattr("context_live_translator.main_window.list_audio_sources", lambda: [])
    window = MainWindow(AppConfig(obs_overlay_port=9876))
    assert window.overlay_url.text() == "http://127.0.0.1:9876/overlay"
    assert window.overlay_max_lines.value() == 3
    assert not window.overlay_show_source.isChecked()
    assert not window.overlay_preview.isEnabled()
    window.controller.shutdown()
    window.deleteLater()


def test_gui_revision_updates_existing_row(qcore_app) -> None:
    window = MainWindow(AppConfig())
    item = TranscriptSegment(
        "same-id",
        1,
        2,
        "en",
        LanguageSpec("zh-TW", "繁中"),
        "raw",
        "raw",
        "初譯",
        status=SegmentStatus.PROVISIONAL,
    )
    window._show_segment(item)  # noqa: SLF001
    item.translation = "修訂"
    item.revision = 1
    window._show_segment(item)  # noqa: SLF001
    assert window.timeline.count() == 1
    assert "修訂" in window.segment_items["same-id"][1].translation_label.text()
    window.controller.shutdown()
    window.deleteLater()


def test_gui_builds_independent_controls_for_each_audio_route(monkeypatch, qcore_app) -> None:
    monkeypatch.setattr("context_live_translator.main_window.list_audio_sources", lambda: [])
    config = AppConfig(
        audio_routes=[
            AudioRouteConfig("self", "自己的麥克風", source_language="zh"),
            AudioRouteConfig("friend", "Discord 朋友", source_language="en"),
        ]
    )
    window = MainWindow(config)
    assert list(window.route_cards) == ["self", "friend"]
    assert window.route_cards["self"].language_combo.currentData() == "zh"
    assert window.route_cards["friend"].language_combo.currentData() == "en"
    window._update_route_level("friend", 0.5)  # noqa: SLF001
    assert window.route_cards["friend"].level.value() == 500
    window.controller.shutdown()
    window.deleteLater()


def test_repeated_start_configuration_preserves_live_route_object(
    monkeypatch, qcore_app
) -> None:
    monkeypatch.setattr("context_live_translator.main_window.list_audio_sources", lambda: [])
    window = MainWindow(
        AppConfig(audio_routes=[AudioRouteConfig("main", "Main", source_language="en")])
    )
    live_route = window.config.audio_routes[0]
    card = window.route_cards["main"]
    card.language_combo.setCurrentIndex(card.language_combo.findData("ja"))

    assert window._read_widgets()  # noqa: SLF001
    assert window.config.audio_routes[0] is live_route
    assert live_route.source_language == "ja"

    card.language_combo.setCurrentIndex(card.language_combo.findData("ko"))
    assert window._read_widgets()  # noqa: SLF001
    assert window.config.audio_routes[0] is live_route
    assert live_route.source_language == "ko"
    window.controller.shutdown()
    window.deleteLater()
