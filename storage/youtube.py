# pip install yt-dlp
"""YouTube download utilities."""
from __future__ import annotations

import re
from pathlib import Path

import yt_dlp

YOUTUBE_URL_RE = re.compile(r"^(https?://)?(www\.)?(youtube\.com/watch\?v=[\w-]{6,}|youtu\.be/[\w-]{6,})(?:[&?].*)?$", re.IGNORECASE)


def _slugify_filename(value: str) -> str:
    """Convert text into a filesystem-friendly slug."""
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-").lower()
    return slug or "youtube-video"


def download_youtube_video(url: str, output_dir: str) -> str:
    """Download a public YouTube video and return absolute local path."""
    if not YOUTUBE_URL_RE.match(url.strip()):
        raise ValueError("Invalid YouTube URL")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    output_template = str((out_dir / "%(title)s.%(ext)s").resolve())
    options = {
        "format": "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4][height<=1080]/best[height<=1080]",
        "outtmpl": output_template,
        "restrictfilenames": True,
        "noplaylist": True,
        "quiet": True,
    }

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url.strip(), download=True)
            downloaded_path = Path(ydl.prepare_filename(info)).resolve()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"yt-dlp failed: {exc}") from exc

    safe_name = f"{_slugify_filename(downloaded_path.stem)}.mp4"
    safe_path = downloaded_path.with_name(safe_name)
    if downloaded_path != safe_path:
        downloaded_path.rename(safe_path)
    return str(safe_path)
