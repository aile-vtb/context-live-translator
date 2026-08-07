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
            return "warning", f"localhost:{port} 已有服務回應；啟動前請關閉或更換連接埠"
    except httpx.HTTPError:
        pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as exc:
            return "error", f"localhost:{port} 無法使用：{exc}"
    return "ok", f"localhost:{port} 可用"


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
            return "ok", f"localhost:{port} Overlay 服務運作中"
        return "error", f"localhost:{port} 已由其他服務使用"
    except (httpx.HTTPError, ValueError):
        pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as exc:
            return "error", f"localhost:{port} 無法使用：{exc}"
    return "ok", f"localhost:{port} 可供 OBS Overlay 使用"


def run_doctor(config: AppConfig) -> list[DiagnosticCheck]:
    checks: list[DiagnosticCheck] = []
    checks.append(
        DiagnosticCheck(
            "Platform",
            "ok" if sys.platform == "win32" else "warning",
            f"{platform.system()} {platform.release()}；v1 正式支援 Windows 10/11",
        )
    )
    supported_python = (3, 10) <= sys.version_info[:2] < (3, 13)
    checks.append(
        DiagnosticCheck(
            "Python",
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
        detail = f"CTranslate2 {ctranslate2.__version__}；CUDA 裝置 {cuda_count}"
        missing_libraries = missing_cuda_libraries(cuda_paths) if cuda_count else ()
        if missing_libraries:
            level = "error" if config.whisper_device == "cuda" else "warning"
            detail += (
                "；缺少 "
                + "、".join(missing_libraries)
                + "。請保留 llama.cpp CUDA DLL，或執行 setup-gpu.cmd"
            )
        elif not cuda_count:
            detail += "；可使用 CPU，但不保證即時"
        checks.append(DiagnosticCheck("Compute", level, detail))
    except Exception as exc:
        checks.append(DiagnosticCheck("Compute", "error", f"CTranslate2 無法載入：{exc}"))
    try:
        inputs = list_input_sources()
        checks.append(DiagnosticCheck("Audio input", "ok", f"找到 {len(inputs)} 個輸入來源"))
    except Exception as exc:
        checks.append(DiagnosticCheck("Audio input", "error", str(exc)))
    try:
        loopbacks = list_loopback_sources()
        checks.append(
            DiagnosticCheck(
                "WASAPI loopback",
                "ok" if loopbacks else "warning",
                f"找到 {len(loopbacks)} 個系統播放端點",
            )
        )
    except Exception as exc:
        checks.append(DiagnosticCheck("WASAPI loopback", "warning", str(exc)))
    whisper_validation = validate_whisper_model(config.whisper_model_path)
    checks.extend(
        [
            DiagnosticCheck(
                "Whisper model",
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
                config.llama_server_path or "尚未設定 llama-server.exe",
            ),
            DiagnosticCheck(
                "GGUF model",
                (
                    "ok"
                    if config.llama_model_path
                    and Path(config.llama_model_path).is_file()
                    else "error"
                ),
                (
                    f"{config.llama_model_path}；profile={model_profile(config.llama_model_path)}"
                    if config.llama_model_path
                    else "尚未設定本機 GGUF"
                ),
            ),
        ]
    )
    level, detail = _check_port(config.llama_port)
    checks.append(DiagnosticCheck("llama.cpp port", level, detail))
    level, detail = _check_overlay_port(config.obs_overlay_port)
    checks.append(DiagnosticCheck("OBS overlay port", level, detail))
    checks.append(
        DiagnosticCheck(
            "Audio routes",
            "ok" if any(route.enabled for route in config.audio_routes) else "error",
            f"設定 {len(config.audio_routes)} 路；"
            f"啟用 {sum(route.enabled for route in config.audio_routes)} 路",
        )
    )
    checks.append(
        DiagnosticCheck(
            "Network policy",
            "ok",
            "翻譯與 OBS Overlay 固定為 127.0.0.1；模型下載連線 Hugging Face；"
            "開啟 About／檢查更新時連線 GitHub API",
        )
    )
    return checks


def format_checks(checks: list[DiagnosticCheck]) -> str:
    icons = {"ok": "OK", "warning": "WARN", "error": "ERROR"}
    return "\n".join(f"[{icons[check.level]}] {check.name}: {check.detail}" for check in checks)
