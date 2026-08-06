from pathlib import Path
from types import SimpleNamespace

import pytest

from context_live_translator import model_manager


def write_model(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for filename in model_manager.WHISPER_REQUIRED_FILES:
        size = 1_000_001 if filename == "model.bin" else 1
        (directory / filename).write_bytes(b"x" * size)


def test_validate_and_discover_managed_and_huggingface_cache(
    tmp_path, monkeypatch
) -> None:
    managed = tmp_path / "managed" / "whisper"
    cached = tmp_path / "cache-small"
    write_model(managed / "small")
    write_model(cached)
    monkeypatch.setattr(model_manager, "MODELS_DIR", tmp_path / "managed")
    revision = SimpleNamespace(snapshot_path=str(cached))
    repo = SimpleNamespace(
        repo_id="Systran/faster-whisper-small", revisions=[revision]
    )
    monkeypatch.setattr(
        model_manager, "scan_cache_dir", lambda: SimpleNamespace(repos=[repo])
    )

    discovered = model_manager.discover_whisper_models()

    assert [(item.key, item.origin) for item in discovered] == [
        ("small", "managed"),
        ("small", "huggingface-cache"),
    ]
    assert model_manager.validate_whisper_model(cached).valid


def test_explicit_download_uses_staging_then_installs(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(model_manager, "MODELS_DIR", tmp_path / "models")
    monkeypatch.setattr(
        model_manager.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(free=10_000_000_000),
    )
    downloads: list[str] = []

    def fake_download(*, filename: str, local_dir: Path, **kwargs: object) -> str:
        downloads.append(filename)
        destination = Path(local_dir) / filename
        size = 1_000_001 if filename == "model.bin" else 1
        destination.write_bytes(b"x" * size)
        return str(destination)

    monkeypatch.setattr(model_manager, "hf_hub_download", fake_download)
    progress: list[tuple[int, str]] = []

    installed = model_manager.download_whisper_model(
        "small", lambda percent, message: progress.append((percent, message))
    )

    assert downloads == list(model_manager.WHISPER_REQUIRED_FILES)
    assert installed == tmp_path / "models" / "whisper" / "small"
    assert model_manager.validate_whisper_model(installed).valid
    assert progress[-1][0] == 100
    assert not (installed.parent / ".small.download").exists()


def test_download_can_be_cancelled_before_network(tmp_path, monkeypatch) -> None:
    import threading

    monkeypatch.setattr(model_manager, "MODELS_DIR", tmp_path / "models")
    event = threading.Event()
    event.set()
    with pytest.raises(model_manager.DownloadCancelled):
        model_manager.download_whisper_model("small", cancel_event=event)
