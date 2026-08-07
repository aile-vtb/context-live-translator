from string import Formatter

from context_live_translator.i18n import (
    ENGLISH,
    JAPANESE,
    normalize_ui_language,
    set_ui_language,
    tr,
)


def fields(template: str) -> set[str]:
    return {
        field_name
        for _, field_name, _, _ in Formatter().parse(template)
        if field_name
    }


def test_translation_catalogs_have_matching_keys_and_placeholders() -> None:
    assert ENGLISH.keys() == JAPANESE.keys()
    for source in ENGLISH:
        assert fields(ENGLISH[source]) == fields(source)
        assert fields(JAPANESE[source]) == fields(source)


def test_translation_and_invalid_language_fallback() -> None:
    try:
        set_ui_language("en")
        assert tr("開始") == "Start"
        assert tr("音訊來源 {number}", number=2) == "Audio source 2"
        assert tr("正在監聽「{label}」：{source}", label="Mic", source="ADAT") == (
            "Monitoring “Mic”: ADAT"
        )
        set_ui_language("ja")
        assert tr("重新掃描") == "再スキャン"
        assert normalize_ui_language("invalid") == "zh-TW"
    finally:
        set_ui_language("zh-TW")
