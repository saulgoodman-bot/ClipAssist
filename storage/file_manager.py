# pip install boto3
"""Storage backend abstraction for local disk and optional S3."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
import boto3
from botocore.exceptions import ClientError

from core.config import BASE_DIR, OUTPUT_DIR, S3_BUCKET, S3_ENDPOINT_URL, TMP_DIR, UPLOAD_DIR


class StorageBackend(ABC):
    """Abstract storage backend interface."""

    @abstractmethod
    def save_upload(self, file_bytes: bytes, filename: str) -> str:
        """Save uploaded file bytes and return storage location string."""

    @abstractmethod
    def cleanup_paths(self, *paths: str) -> None:
        """Delete paths or object keys if present."""

    @abstractmethod
    def ensure_dirs(self) -> None:
        """Ensure required local directories exist when applicable."""


class LocalStorage(StorageBackend):
    """Local filesystem storage implementation."""

    def save_upload(self, file_bytes: bytes, filename: str) -> str:
        self.ensure_dirs()
        file_path = UPLOAD_DIR / filename
        file_path.write_bytes(file_bytes)
        return str(file_path.resolve())

    def cleanup_paths(self, *paths: str) -> None:
        for raw in paths:
            if not raw:
                continue
            path = Path(raw)
            if path.exists() and path.is_file():
                path.unlink()

    def ensure_dirs(self) -> None:
        for directory in (BASE_DIR, UPLOAD_DIR, OUTPUT_DIR, TMP_DIR):
            directory.mkdir(parents=True, exist_ok=True)


class S3Storage(StorageBackend):
    """S3 object storage implementation."""

    def __init__(self) -> None:
        if not S3_BUCKET:
            raise RuntimeError('S3_BUCKET_NAME must be set for S3Storage')
        self.bucket = S3_BUCKET
        self.client = boto3.client('s3', endpoint_url=S3_ENDPOINT_URL or None)

    def save_upload(self, file_bytes: bytes, filename: str) -> str:
        key = f'uploads/{filename}'
        try:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=file_bytes)
        except ClientError as exc:
            raise RuntimeError(f'Failed to upload bytes to S3 key {key}: {exc}') from exc
        return key

    def upload_file(self, local_path: str, s3_key: str) -> str:
        """Upload a local file to S3 and return the S3 key."""
        try:
            self.client.upload_file(str(Path(local_path)), self.bucket, s3_key)
        except ClientError as exc:
            raise RuntimeError(f'Failed to upload file to S3 key {s3_key}: {exc}') from exc
        return s3_key

    def generate_presigned_url(self, s3_key: str, expires: int = 3600) -> str:
        """Generate presigned GET URL for an S3 key."""
        try:
            return self.client.generate_presigned_url(
                'get_object', Params={'Bucket': self.bucket, 'Key': s3_key}, ExpiresIn=expires
            )
        except ClientError as exc:
            raise RuntimeError(f'Failed to generate presigned URL for {s3_key}: {exc}') from exc

    def download_to_tmp(self, s3_key: str) -> str:
        """Download an S3 object to TMP_DIR and return local path."""
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        dst = TMP_DIR / Path(s3_key).name
        try:
            self.client.download_file(self.bucket, s3_key, str(dst))
        except ClientError as exc:
            raise RuntimeError(f'Failed to download S3 key {s3_key}: {exc}') from exc
        return str(dst.resolve())

    def cleanup_paths(self, *paths: str) -> None:
        for key in paths:
            if not key:
                continue
            try:
                self.client.delete_object(Bucket=self.bucket, Key=key)
            except ClientError as exc:
                raise RuntimeError(f'Failed to delete S3 key {key}: {exc}') from exc

    def ensure_dirs(self) -> None:
        TMP_DIR.mkdir(parents=True, exist_ok=True)


_backend: StorageBackend = S3Storage() if S3_BUCKET else LocalStorage()


def save_upload(file_bytes: bytes, filename: str) -> str:
    """Save upload using active backend."""
    return _backend.save_upload(file_bytes, filename)


def cleanup_paths(*paths: str) -> None:
    """Cleanup files/keys using active backend."""
    _backend.cleanup_paths(*paths)


def ensure_dirs() -> None:
    """Ensure active backend directories are available."""
    _backend.ensure_dirs()


def generate_presigned_url(s3_key: str, expires: int = 3600) -> str:
    """Generate a URL for downloading a storage object."""
    if isinstance(_backend, S3Storage):
        return _backend.generate_presigned_url(s3_key, expires=expires)
    return Path(s3_key).resolve().as_uri()
