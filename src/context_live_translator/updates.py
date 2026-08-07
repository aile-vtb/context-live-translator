from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from typing import Any

from packaging.version import InvalidVersion, Version

from . import __version__
from .i18n import tr

PACKAGE_NAME = "context-live-translator"
PROJECT_URL = "https://github.com/aile-vtb/context-live-translator"
RELEASES_URL = f"{PROJECT_URL}/releases"
RELEASES_API_URL = "https://api.github.com/repos/aile-vtb/context-live-translator/releases"


class UpdateState(str, Enum):
    UPDATE_AVAILABLE = "update_available"
    CURRENT = "current"
    LOCAL_NEWER = "local_newer"


@dataclass(frozen=True)
class ReleaseInfo:
    version: Version
    tag_name: str
    html_url: str
    prerelease: bool
    published_at: str


def installed_version() -> str:
    try:
        metadata_version = package_version(PACKAGE_NAME)
    except PackageNotFoundError:
        return __version__
    return metadata_version if metadata_version == __version__ else __version__


def parse_tag_version(tag_name: str) -> Version:
    normalized = tag_name.strip()
    if normalized.lower().startswith("v"):
        normalized = normalized[1:]
    return Version(normalized)


def select_latest_release(payload: Any) -> ReleaseInfo:
    if not isinstance(payload, list):
        raise ValueError(tr("GitHub Release 回應格式不正確"))
    candidates: list[ReleaseInfo] = []
    for item in payload:
        if not isinstance(item, dict) or item.get("draft") is True:
            continue
        tag_name = item.get("tag_name")
        if not isinstance(tag_name, str):
            continue
        try:
            release_version = parse_tag_version(tag_name)
        except InvalidVersion:
            continue
        html_url = item.get("html_url")
        if not isinstance(html_url, str) or not html_url.startswith(
            PROJECT_URL + "/releases/"
        ):
            html_url = RELEASES_URL
        published_at = item.get("published_at")
        candidates.append(
            ReleaseInfo(
                version=release_version,
                tag_name=tag_name,
                html_url=html_url,
                prerelease=bool(item.get("prerelease")),
                published_at=published_at if isinstance(published_at, str) else "",
            )
        )
    if not candidates:
        raise ValueError(tr("GitHub 沒有可用的 Release"))
    return max(candidates, key=lambda release: release.version)


def compare_release(local_version: str, release: ReleaseInfo) -> UpdateState:
    local = parse_tag_version(local_version)
    if release.version > local:
        return UpdateState.UPDATE_AVAILABLE
    if release.version < local:
        return UpdateState.LOCAL_NEWER
    return UpdateState.CURRENT
