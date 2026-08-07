from packaging.version import Version

from context_live_translator.config import AppConfig
from context_live_translator.main_window import MainWindow
from context_live_translator.models import (
    AudioRouteConfig,
    LanguageSpec,
    SegmentStatus,
    TranscriptSegment,
)
from context_live_translator.updates import ReleaseInfo


def test_gui_has_standalone_translation_tabs(monkeypatch, qcore_app) -> None:
    monkeypatch.setattr("context_live_translator.main_window.list_audio_sources", lambda: [])
    window = MainWindow(AppConfig())
    assert [window.tabs.tabText(index) for index in range(window.tabs.count())] == [
        "即時翻譯",
        "模型與進階",
        "OBS Overlay",
        "診斷",
        "About",
    ]
    assert window.timeline.objectName() == "timeline"
    assert window.target_combo.findData("__custom__") >= 0
    assert not window.windowIcon().isNull()
    assert window.about_local_version.text().startswith("v0.3.5")
    assert window.about_latest_version.text() == "尚未檢查"
    assert window._update_reply is None  # noqa: SLF001
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


def test_gui_language_selector_retranslates_all_tabs(monkeypatch, qcore_app) -> None:
    monkeypatch.setattr("context_live_translator.main_window.list_audio_sources", lambda: [])
    monkeypatch.setattr("context_live_translator.main_window.save_config", lambda config: None)
    window = MainWindow(AppConfig())
    assert [window.ui_language_combo.itemText(index) for index in range(3)] == [
        "中文",
        "English",
        "日本語",
    ]

    window.ui_language_combo.setCurrentIndex(window.ui_language_combo.findData("en"))
    assert window.config.ui_language == "en"
    assert [window.tabs.tabText(index) for index in range(window.tabs.count())] == [
        "Live Translation",
        "Models & Advanced",
        "OBS Overlay",
        "Diagnostics",
        "About",
    ]
    assert window.start_button.text() == "Start"
    assert window.add_route_button.text() == "Add audio source"
    assert window.about_check_button.text() == "Check again"
    assert window.target_combo.itemText(window.target_combo.findData("zh-TW")) == (
        "Traditional Chinese (Taiwan)"
    )

    window.ui_language_combo.setCurrentIndex(window.ui_language_combo.findData("ja"))
    assert window.config.ui_language == "ja"
    assert window.tabs.tabText(0) == "リアルタイム翻訳"
    assert window.tabs.tabText(1) == "モデルと詳細設定"
    assert window.tabs.tabText(3) == "診断"
    assert window.start_button.text() == "開始"
    assert window.about_check_button.text() == "再確認"
    window.controller.shutdown()
    window.deleteLater()


def test_about_page_displays_update_and_offline_states(monkeypatch, qcore_app) -> None:
    monkeypatch.setattr("context_live_translator.main_window.list_audio_sources", lambda: [])
    window = MainWindow(AppConfig())
    window._show_update_release(  # noqa: SLF001
        ReleaseInfo(
            Version("0.3.6"),
            "v0.3.6",
            "https://github.com/aile-vtb/context-live-translator/releases/tag/v0.3.6",
            True,
            "",
        )
    )
    assert window.about_latest_version.text() == "v0.3.6（Pre-release）"
    assert "有新版本" in window.about_update_status.text()
    window._show_update_error("offline")  # noqa: SLF001
    assert window.about_latest_version.text() == "無法取得"
    assert "不影響離線使用" in window.about_update_status.text()
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
