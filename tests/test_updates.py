import pytest
from packaging.version import InvalidVersion, Version

from context_live_translator.updates import (
    UpdateState,
    compare_release,
    parse_tag_version,
    select_latest_release,
)


def release(tag: str, *, prerelease: bool = False, draft: bool = False) -> dict:
    return {
        "tag_name": tag,
        "html_url": (
            "https://github.com/aile-vtb/context-live-translator/releases/tag/" + tag
        ),
        "prerelease": prerelease,
        "draft": draft,
        "published_at": "2026-08-07T00:00:00Z",
    }


def test_tag_parser_accepts_v_prefix_and_prerelease() -> None:
    assert parse_tag_version("v0.3.4") == Version("0.3.4")
    assert parse_tag_version("0.4.0-beta.1") == Version("0.4.0b1")


def test_release_selection_includes_prerelease_and_ignores_draft() -> None:
    result = select_latest_release(
        [
            release("v0.3.3"),
            release("v0.4.0", prerelease=True),
            release("v9.0.0", draft=True),
            release("not-a-version"),
        ]
    )
    assert result.version == Version("0.4.0")
    assert result.prerelease


@pytest.mark.parametrize(
    ("local", "remote", "expected"),
    [
        ("0.3.3", "v0.3.4", UpdateState.UPDATE_AVAILABLE),
        ("0.3.3", "v0.3.3", UpdateState.CURRENT),
        ("0.3.3", "v0.3.2", UpdateState.LOCAL_NEWER),
    ],
)
def test_release_comparison(local, remote, expected) -> None:
    assert compare_release(local, select_latest_release([release(remote)])) == expected


def test_release_selection_rejects_unusable_payload() -> None:
    with pytest.raises(ValueError, match="格式不正確"):
        select_latest_release({})
    with pytest.raises(ValueError, match="沒有可用"):
        select_latest_release([release("invalid")])
    with pytest.raises(InvalidVersion):
        parse_tag_version("not-a-version")
