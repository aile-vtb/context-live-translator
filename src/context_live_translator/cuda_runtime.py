from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Iterable
from pathlib import Path

_DLL_DIRECTORY_HANDLES: list[object] = []
_REGISTERED_DIRECTORIES: set[str] = set()


def cuda_library_directories(extra_paths: Iterable[str | Path] = ()) -> tuple[Path, ...]:
    """Return existing directories that may contain CUDA runtime DLLs."""
    candidates: list[Path] = []
    for raw_path in extra_paths:
        if not raw_path:
            continue
        path = Path(raw_path).expanduser()
        candidates.append(path.parent if path.suffix.lower() == ".exe" else path)

    site_packages = Path(sys.prefix) / "Lib" / "site-packages"
    candidates.extend(
        [
            site_packages / "nvidia" / "cuda_runtime" / "bin",
            site_packages / "nvidia" / "cublas" / "bin",
            site_packages / "nvidia" / "cudnn" / "bin",
            site_packages / "ctranslate2",
        ]
    )
    for variable in ("CUDA_PATH", "CUDA_PATH_V12_4", "CUDA_PATH_V12_3"):
        value = os.environ.get(variable)
        if value:
            candidates.append(Path(value) / "bin")

    result: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        key = os.path.normcase(str(resolved))
        if resolved.is_dir() and key not in seen:
            seen.add(key)
            result.append(resolved)
    return tuple(result)


def register_cuda_dll_directories(
    extra_paths: Iterable[str | Path] = (),
) -> tuple[Path, ...]:
    """Make local CUDA DLL folders visible to Python on Windows.

    Python 3.8+ no longer searches every PATH entry for extension dependencies,
    so ``os.add_dll_directory`` is required. Handles are kept for the process
    lifetime because closing one removes the directory from the DLL search path.
    """
    directories = cuda_library_directories(extra_paths)
    if os.name != "nt":
        return directories

    current_path = os.environ.get("PATH", "")
    current_parts = current_path.split(os.pathsep) if current_path else []
    current_keys = {os.path.normcase(part) for part in current_parts if part}
    prepend: list[str] = []
    for directory in directories:
        text = str(directory)
        key = os.path.normcase(text)
        if key not in current_keys:
            prepend.append(text)
            current_keys.add(key)
        if key in _REGISTERED_DIRECTORIES:
            continue
        try:
            _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(text))
            _REGISTERED_DIRECTORIES.add(key)
        except (AttributeError, FileNotFoundError, OSError):
            continue
    if prepend:
        os.environ["PATH"] = os.pathsep.join([*prepend, *current_parts])
    return directories


def missing_cuda_libraries(
    extra_paths: Iterable[str | Path] = (),
) -> tuple[str, ...]:
    directories = register_cuda_dll_directories(extra_paths)
    missing: list[str] = []
    for filename in ("cublas64_12.dll", "cudnn64_9.dll"):
        if shutil.which(filename) or any((directory / filename).is_file() for directory in directories):
            continue
        missing.append(filename)
    return tuple(missing)
