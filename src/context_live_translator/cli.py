from __future__ import annotations

import argparse
import os
import sys

from .config import load_config
from .doctor import format_checks, run_doctor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="context-live-translator")
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Run read-only environment diagnostics and exit.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config()
    if args.doctor:
        checks = run_doctor(config)
        print(format_checks(checks))
        return 1 if any(check.level == "error" for check in checks) else 0
    if sys.platform != "win32":
        print("Warning: v1 is tested on Windows 10/11 only.", file=sys.stderr)
    else:
        try:
            from ctypes import windll

            windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "aile-vtb.ContextLiveTranslator"
            )
        except (AttributeError, OSError):
            pass
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    from PySide6.QtWidgets import QApplication

    from .main_window import MainWindow
    from .resources import application_icon

    app = QApplication(sys.argv if argv is None else ["context-live-translator", *argv])
    app.setApplicationName("Context Live Translator")
    app.setApplicationDisplayName("Context Live Translator")
    app.setWindowIcon(application_icon())
    window = MainWindow(config)
    window.show()
    return app.exec()
