from __future__ import annotations

import shutil
from pathlib import Path

BASE_DIR = Path("data")
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
TMP_DIR = BASE_DIR / "tmp"


def ensure_dirs() -> None:
    for directory in (UPLOAD_DIR, OUTPUT_DIR, TMP_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def save_upload(file_bytes: bytes, filename: str) -> str:
    ensure_dirs()
    file_path = UPLOAD_DIR / filename
    file_path.write_bytes(file_bytes)
    return str(file_path)


def cleanup_paths(*paths: str) -> None:
    for raw_path in paths:
        path = Path(raw_path)
        if path.exists() and path.is_file():
            path.unlink()


def clear_all_local_data() -> None:
    if BASE_DIR.exists():
        shutil.rmtree(BASE_DIR)
