from __future__ import annotations

import os
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from huggingface_hub import hf_hub_download, scan_cache_dir
from tqdm.auto import tqdm

from .config import MODELS_DIR

WHISPER_REQUIRED_FILES = ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt")


@dataclass(frozen=True)
class WhisperModelSpec:
    key: str
    display_name: str
    repo_id: str
    approximate_bytes: int
    file_sizes: dict[str, int]


WHISPER_MODELS: dict[str, WhisperModelSpec] = {
    "small": WhisperModelSpec(
        key="small",
        display_name="faster-whisper-small（建議即時使用）",
        repo_id="Systran/faster-whisper-small",
        approximate_bytes=486_000_000,
        file_sizes={
            "model.bin": 483_546_902,
            "config.json": 2_370,
            "tokenizer.json": 2_203_239,
            "vocabulary.txt": 459_861,
        },
    ),
    "medium": WhisperModelSpec(
        key="medium",
        display_name="faster-whisper-medium（較慢、較大）",
        repo_id="Systran/faster-whisper-medium",
        approximate_bytes=1_531_000_000,
        file_sizes={
            "model.bin": 1_527_906_378,
            "config.json": 2_257,
            "tokenizer.json": 2_203_239,
            "vocabulary.txt": 459_861,
        },
    ),
}


@dataclass(frozen=True)
class ModelValidation:
    path: Path
    valid: bool
    missing_files: tuple[str, ...]
    total_bytes: int

    @property
    def message(self) -> str:
        if self.valid:
            return f"Whisper CTranslate2 模型有效：{self.path}"
        if not str(self.path).strip() or str(self.path) == ".":
            return "尚未設定 Whisper CTranslate2 模型目錄"
        return "Whisper 模型不完整，缺少或無效：" + "、".join(self.missing_files)


@dataclass(frozen=True)
class DiscoveredWhisperModel:
    key: str
    path: Path
    origin: str
    total_bytes: int


class DownloadCancelled(RuntimeError):
    pass


def managed_whisper_path(model_key: str) -> Path:
    return MODELS_DIR / "whisper" / model_key


def validate_whisper_model(path: str | Path) -> ModelValidation:
    if not str(path).strip():
        return ModelValidation(Path(), False, WHISPER_REQUIRED_FILES, 0)
    directory = Path(path).expanduser()
    missing: list[str] = []
    total = 0
    for filename in WHISPER_REQUIRED_FILES:
        candidate = directory / filename
        try:
            size = candidate.stat().st_size
        except OSError:
            missing.append(filename)
            continue
        if size <= 0 or (filename == "model.bin" and size < 1_000_000):
            missing.append(filename)
            continue
        total += size
    return ModelValidation(directory, not missing, tuple(missing), total)


def discover_whisper_models() -> list[DiscoveredWhisperModel]:
    found: dict[Path, DiscoveredWhisperModel] = {}
    for key in WHISPER_MODELS:
        path = managed_whisper_path(key)
        validation = validate_whisper_model(path)
        if validation.valid:
            resolved = path.resolve()
            found[resolved] = DiscoveredWhisperModel(
                key, resolved, "managed", validation.total_bytes
            )
    try:
        cache = scan_cache_dir()
    except Exception:
        cache = None
    if cache is not None:
        repo_keys = {spec.repo_id: key for key, spec in WHISPER_MODELS.items()}
        for repo in cache.repos:
            key = repo_keys.get(repo.repo_id)
            if key is None:
                continue
            for revision in repo.revisions:
                path = Path(revision.snapshot_path)
                validation = validate_whisper_model(path)
                if not validation.valid:
                    continue
                resolved = path.resolve()
                found[resolved] = DiscoveredWhisperModel(
                    key, resolved, "huggingface-cache", validation.total_bytes
                )
    return sorted(
        found.values(),
        key=lambda item: (
            0 if item.key == "small" else 1,
            0 if item.origin == "managed" else 1,
            str(item.path).lower(),
        ),
    )


def best_existing_whisper_model() -> DiscoveredWhisperModel | None:
    models = discover_whisper_models()
    return models[0] if models else None


def download_whisper_model(
    model_key: str,
    on_progress: Callable[[int, str], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> Path:
    try:
        spec = WHISPER_MODELS[model_key]
    except KeyError as exc:
        raise ValueError(f"未知 Whisper 模型：{model_key}") from exc
    progress = on_progress or (lambda percent, message: None)
    canceled = cancel_event or threading.Event()
    target = managed_whisper_path(model_key)
    validation = validate_whisper_model(target)
    if validation.valid:
        progress(100, f"模型已存在：{target}")
        return target

    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = parent / f".{model_key}.download"
    staging.mkdir(parents=True, exist_ok=True)
    current_staging_bytes = sum(
        item.stat().st_size for item in staging.rglob("*") if item.is_file()
    )
    required_free = max(0, round(spec.approximate_bytes * 1.10) - current_staging_bytes)
    free = shutil.disk_usage(parent).free
    if free < required_free:
        raise OSError(
            f"磁碟空間不足：至少還需要約 {required_free / 1_000_000:.0f} MB，"
            f"目前可用 {free / 1_000_000:.0f} MB"
        )

    completed = 0
    total = sum(spec.file_sizes.values())

    def progress_class(filename: str, base: int, expected: int) -> type[tqdm]:
        class CallbackTqdm(tqdm):
            def update(self, count: int = 1) -> bool | None:
                if canceled.is_set():
                    raise DownloadCancelled("使用者取消模型下載")
                result = super().update(count)
                current = min(expected, int(self.n))
                percent = min(99, round((base + current) / total * 100))
                progress(percent, f"下載 {filename}：{percent}%")
                return result

        return CallbackTqdm

    try:
        for filename in WHISPER_REQUIRED_FILES:
            if canceled.is_set():
                raise DownloadCancelled("使用者取消模型下載")
            expected = spec.file_sizes[filename]
            existing = staging / filename
            if existing.is_file() and existing.stat().st_size >= expected:
                completed += expected
                progress(round(completed / total * 100), f"已驗證 {filename}")
                continue
            progress(round(completed / total * 100), f"準備下載 {filename}")
            hf_hub_download(
                repo_id=spec.repo_id,
                filename=filename,
                local_dir=staging,
                library_name="context-live-translator",
                tqdm_class=progress_class(filename, completed, expected),
            )
            completed += expected
            progress(min(99, round(completed / total * 100)), f"已下載 {filename}")
        validation = validate_whisper_model(staging)
        if not validation.valid:
            raise RuntimeError(
                "下載完成但模型不完整，缺少：" + ", ".join(validation.missing_files)
            )
        if target.exists():
            backup = parent / f".{model_key}.previous"
            if backup.exists():
                shutil.rmtree(backup)
            os.replace(target, backup)
            try:
                os.replace(staging, target)
            except Exception:
                os.replace(backup, target)
                raise
            else:
                shutil.rmtree(backup)
        else:
            os.replace(staging, target)
        progress(100, f"模型安裝完成：{target}")
        return target
    except DownloadCancelled:
        progress(0, "模型下載已取消；暫存檔保留供下次續傳")
        raise
