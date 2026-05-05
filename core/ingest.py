"""What changed: Added YouTube URL validation and download helper using yt-dlp."""
from __future__ import annotations

import re
from pathlib import Path

from yt_dlp import YoutubeDL

_YOUTUBE_URL_RE = re.compile(
    r"^(https?://)?(www\.)?(youtube\.com/watch\?v=[\w-]{11}|youtu\.be/[\w-]{11})([&?].*)?$",
    re.IGNORECASE,
)


def download_youtube(url: str, output_dir: str) -> str:
    if not _YOUTUBE_URL_RE.match(url.strip()):
        raise ValueError("Invalid YouTube URL. Expected a youtube.com or youtu.be video URL.")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        "format": "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4][height<=1080]/best[height<=1080]",
        "merge_output_format": "mp4",
        "outtmpl": str(output_path / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)

    final_path = Path(filename)
    if final_path.suffix.lower() != ".mp4":
        candidate = final_path.with_suffix(".mp4")
        if candidate.exists():
            final_path = candidate

    return str(final_path)
