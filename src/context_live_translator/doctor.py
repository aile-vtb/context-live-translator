from __future__ import annotations

import platform
import socket
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx

from .audio import list_input_sources, list_loopback_sources
from .config import AppConfig
from .cuda_runtime import missing_cuda_libraries, register_cuda_dll_directories
from .i18n import set_ui_language, tr
from .model_manager import validate_whisper_model
from .translator import model_profile


@dataclass(frozen=True)
class DiagnosticCheck:
    name: str
    level: str
    detail: str


def _check_port(port: int) -> tuple[str, str]:
    try:
        response = httpx.get(
            f"http://127.0.0.1:{port}/health",
            timeout=1,
            trust_env=False,
        )
        if response.status_code == 200:
            return "warning", tr("localhost:{port} 已有服務回應；啟動前請關閉或更換連接埠", port=port)
    except httpx.HTTPError:
        pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as exc:
            return "error", tr("localhost:{port} 無法使用：{error}", port=port, error=exc)
    return "ok", tr("localhost:{port} 可用", port=port)


def _check_overlay_port(port: int) -> tuple[str, str]:
    try:
        response = httpx.get(
            f"http://127.0.0.1:{port}/health",
            timeout=1,
            trust_env=False,
        )
        data = response.json()
        if (
            response.status_code == 200
            and data.get("service") == "context-live-translator-overlay"
        ):
            return "ok", tr("localhost:{port} Overlay 服務運作中", port=port)
        return "error", tr("localhost:{port} 已由其他服務使用", port=port)
    except (httpx.HTTPError, ValueError):
        pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as exc:
            return "error", tr("localhost:{port} 無法使用：{error}", port=port, error=exc)
    return "ok", tr("localhost:{port} 可供 OBS Overlay 使用", port=port)


def run_doctor(config: AppConfig) -> list[DiagnosticCheck]:
    set_ui_language(config.ui_language)
    checks: list[DiagnosticCheck] = []
    checks.append(
        DiagnosticCheck(
            tr("Platform"),
            "ok" if sys.platform == "win32" else "warning",
            tr(
                "{system} {release}；v1 正式支援 Windows 10/11",
                system=platform.system(),
                release=platform.release(),
            ),
        )
    )
    supported_python = (3, 10) <= sys.version_info[:2] < (3, 13)
    checks.append(
        DiagnosticCheck(
            tr("Python"),
            "ok" if supported_python else "error",
            platform.python_version(),
        )
    )
    try:
        cuda_paths = (config.llama_server_path,) if config.llama_server_path else ()
        register_cuda_dll_directories(cuda_paths)
        import ctranslate2

        cuda_count = ctranslate2.get_cuda_device_count()
        level = "ok" if cuda_count or config.whisper_device != "cuda" else "error"
        detail = tr(
            "CTranslate2 {version}；CUDA 裝置 {count}",
            version=ctranslate2.__version__,
            count=cuda_count,
        )
        missing_libraries = missing_cuda_libraries(cuda_paths) if cuda_count else ()
        if missing_libraries:
            level = "error" if config.whisper_device == "cuda" else "warning"
            detail += tr(
                "；缺少 {libraries}。請保留 llama.cpp CUDA DLL，或執行 setup-gpu.cmd",
                libraries="、".join(missing_libraries),
            )
        elif not cuda_count:
            detail += tr("；可使用 CPU，但不保證即時")
        checks.append(DiagnosticCheck(tr("Compute"), level, detail))
    except Exception as exc:
        checks.append(
            DiagnosticCheck(
                tr("Compute"),
                "error",
                tr("CTranslate2 無法載入：{error}", error=exc),
            )
        )
    try:
        inputs = list_input_sources()
        checks.append(
            DiagnosticCheck(
                tr("Audio input"),
                "ok",
                tr("找到 {count} 個輸入來源", count=len(inputs)),
            )
        )
    except Exception as exc:
        checks.append(DiagnosticCheck(tr("Audio input"), "error", str(exc)))
    try:
        loopbacks = list_loopback_sources()
        checks.append(
            DiagnosticCheck(
                tr("WASAPI loopback"),
                "ok" if loopbacks else "warning",
                tr("找到 {count} 個系統播放端點", count=len(loopbacks)),
            )
        )
    except Exception as exc:
        checks.append(DiagnosticCheck(tr("WASAPI loopback"), "warning", str(exc)))
    whisper_validation = validate_whisper_model(config.whisper_model_path)
    checks.extend(
        [
            DiagnosticCheck(
                tr("Whisper model"),
                "ok" if whisper_validation.valid else "error",
                whisper_validation.message,
            ),
            DiagnosticCheck(
                "llama-server",
                (
                    "ok"
                    if config.llama_server_path
                    and Path(config.llama_server_path).is_file()
                    else "error"
                ),
                config.llama_server_path or tr("尚未設定 llama-server.exe"),
            ),
            DiagnosticCheck(
                tr("GGUF model"),
                (
                    "ok"
                    if config.llama_model_path
                    and Path(config.llama_model_path).is_file()
                    else "error"
                ),
                (
                    f"{config.llama_model_path}；profile={model_profile(config.llama_model_path)}"
                    if config.llama_model_path
                    else tr("尚未設定本機 GGUF")
                ),
            ),
        ]
    )
    level, detail = _check_port(config.llama_port)
    checks.append(DiagnosticCheck(tr("llama.cpp port"), level, detail))
    level, detail = _check_overlay_port(config.obs_overlay_port)
    checks.append(DiagnosticCheck(tr("OBS overlay port"), level, detail))
    checks.append(
        DiagnosticCheck(
            tr("Audio routes"),
            "ok" if any(route.enabled for route in config.audio_routes) else "error",
            tr(
                "設定 {configured} 路；啟用 {enabled} 路",
                configured=len(config.audio_routes),
                enabled=sum(route.enabled for route in config.audio_routes),
            ),
        )
    )
    checks.append(
        DiagnosticCheck(
            tr("Network policy"),
            "ok",
            tr(
                "翻譯與 OBS Overlay 固定為 127.0.0.1；模型下載連線 Hugging Face；開啟 About／檢查更新時連線 GitHub API"
            ),
        )
    )
    return checks


def format_checks(checks: list[DiagnosticCheck]) -> str:
    icons = {"ok": "OK", "warning": "WARN", "error": "ERROR"}
    return "\n".join(f"[{icons[check.level]}] {check.name}: {check.detail}" for check in checks)
