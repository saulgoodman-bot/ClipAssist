"""What changed: Added dual local/S3 storage backend support with upload/output/presign/cleanup helpers."""
from __future__ import annotations

import shutil
from pathlib import Path

import boto3

from core.config import OUTPUT_DIR, S3_BUCKET, S3_ENDPOINT_URL, STORAGE_BACKEND, TMP_DIR, UPLOAD_DIR


def _is_s3() -> bool:
    return STORAGE_BACKEND == "s3"


def _s3_client():
    return boto3.client("s3", endpoint_url=S3_ENDPOINT_URL or None)


def ensure_dirs() -> None:
    for directory in (UPLOAD_DIR, OUTPUT_DIR, TMP_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def save_upload(file_bytes: bytes, filename: str) -> str:
    ensure_dirs()
    if _is_s3():
        if not S3_BUCKET:
            raise RuntimeError("S3_BUCKET must be set when STORAGE_BACKEND=s3")
        key = f"uploads/{filename}"
        _s3_client().put_object(Bucket=S3_BUCKET, Key=key, Body=file_bytes)
        return key

    file_path = UPLOAD_DIR / filename
    file_path.write_bytes(file_bytes)
    return str(file_path)


def save_output(local_path: str, key: str) -> str:
    ensure_dirs()
    if _is_s3():
        if not S3_BUCKET:
            raise RuntimeError("S3_BUCKET must be set when STORAGE_BACKEND=s3")
        _s3_client().upload_file(local_path, S3_BUCKET, key)
        return key

    src = Path(local_path)
    dst = OUTPUT_DIR / key
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != dst.resolve():
        shutil.copy2(src, dst)
    return str(dst)


def get_presigned_url(key: str, expires_seconds: int = 3600) -> str:
    if _is_s3():
        if not S3_BUCKET:
            raise RuntimeError("S3_BUCKET must be set when STORAGE_BACKEND=s3")
        return _s3_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": S3_BUCKET, "Key": key},
            ExpiresIn=expires_seconds,
        )

    return Path(key).resolve().as_uri()


def cleanup_keys(*keys: str) -> None:
    if _is_s3():
        if not S3_BUCKET:
            return
        client = _s3_client()
        for key in keys:
            if key:
                client.delete_object(Bucket=S3_BUCKET, Key=key)
        return

    for raw_path in keys:
        path = Path(raw_path)
        if path.exists() and path.is_file():
            path.unlink()


def clear_all_local_data() -> None:
    base = UPLOAD_DIR.parent
    if base.exists():
        shutil.rmtree(base)
