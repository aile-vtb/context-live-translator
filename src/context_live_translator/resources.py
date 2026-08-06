from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QIcon

PACKAGE_DIR = Path(__file__).resolve().parent
LOGO_PATH = PACKAGE_DIR / "static" / "logo.gif"


def application_icon() -> QIcon:
    """Return the packaged application icon, or an empty icon if unavailable."""
    return QIcon(str(LOGO_PATH))
