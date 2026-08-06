from context_live_translator.resources import LOGO_PATH, application_icon


def test_packaged_logo_is_available(qcore_app) -> None:
    assert LOGO_PATH.is_file()
    assert LOGO_PATH.stat().st_size > 0
    assert not application_icon().isNull()
