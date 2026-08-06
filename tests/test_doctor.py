from context_live_translator.config import AppConfig
from context_live_translator.doctor import DiagnosticCheck, format_checks, run_doctor


def test_format_checks_is_plain_and_actionable() -> None:
    output = format_checks(
        [
            DiagnosticCheck("Python", "ok", "3.11"),
            DiagnosticCheck("GGUF", "error", "missing"),
            DiagnosticCheck("CPU", "warning", "slow"),
        ]
    )
    assert "[OK] Python: 3.11" in output
    assert "[ERROR] GGUF: missing" in output
    assert "[WARN] CPU: slow" in output


def test_default_config_requires_local_model_paths() -> None:
    config = AppConfig()
    assert config.whisper_model_path == ""
    assert config.llama_server_path == ""
    assert config.llama_model_path == ""


def test_empty_whisper_path_is_not_current_directory(monkeypatch) -> None:
    monkeypatch.setattr(
        "context_live_translator.doctor.list_input_sources",
        lambda: [],
    )
    monkeypatch.setattr(
        "context_live_translator.doctor.list_loopback_sources",
        lambda: [],
    )
    monkeypatch.setattr(
        "context_live_translator.doctor._check_port",
        lambda port: ("ok", "available"),
    )
    monkeypatch.setattr(
        "context_live_translator.doctor._check_overlay_port",
        lambda port: ("ok", "available"),
    )
    checks = {check.name: check for check in run_doctor(AppConfig())}
    assert checks["Whisper model"].level == "error"
