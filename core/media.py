from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


# ── Subprocess helper ─────────────────────────────────────────────────────────

def run_cmd(command: list[str]) -> None:
    """Run a shell command, raise CalledProcessError on failure."""
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed (exit {result.returncode}):\n"
            f"  cmd : {' '.join(command)}\n"
            f"  stderr: {result.stderr[-2000:]}"
        )


# ── FFprobe ───────────────────────────────────────────────────────────────────

def ffprobe_metadata(video_path: str) -> dict[str, Any]:
    cmd: list[str] = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        video_path,
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def get_video_dimensions(video_path: str) -> tuple[int, int]:
    """Return (width, height) of the first video stream."""
    meta = ffprobe_metadata(video_path)
    for stream in meta.get("streams", []):
        if stream.get("codec_type") == "video":
            return int(stream["width"]), int(stream["height"])
    raise ValueError(f"No video stream found in {video_path}")


# ── Audio extraction ──────────────────────────────────────────────────────────

def extract_audio_wav(video_path: str, wav_path: str) -> str:
    """
    Extract mono 16kHz WAV — the format faster-whisper expects.
    """
    cmd: list[str] = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vn",               # drop video
        "-ac", "1",          # mono
        "-ar", "16000",      # 16kHz sample rate
        "-c:a", "pcm_s16le", # uncompressed WAV
        wav_path,
    ]
    run_cmd(cmd)
    return wav_path


# ── Video rendering ───────────────────────────────────────────────────────────

def _build_vertical_crop_filter(width: int, height: int) -> str:
    """
    Build an FFmpeg vf filter string that converts any aspect ratio to 9:16 (1080x1920).

    Strategy:
      - If source is already taller than wide (portrait): pad to 9:16.
      - If source is landscape (width >= height): scale so height == 1920,
        then center-crop width to 1080.

    BUG that was here before:
      scale=1080:-2 on a 1920x1080 input gives 1080x607.
      crop=1080:1920 then tries to crop 1920px of height from 607px → crash.
    """
    target_w, target_h = 1080, 1920

    if width >= height:
        # Landscape → scale height to 1920, then center-crop width to 1080
        # scale=-2:1920 preserves aspect ratio and ensures height == 1920.
        # (iw-ow)/2 centers the crop horizontally.
        return f"scale=-2:{target_h},crop={target_w}:{target_h}:(iw-ow)/2:0"
    else:
        # Portrait → scale width to 1080, pad height to 1920 if shorter
        return (
            f"scale={target_w}:-2,"
            f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:black"
        )


def render_clip_with_ass(
    input_video: str,
    output_video: str,
    ass_file: str,
    start: float,
    end: float,
) -> str:
    """
    Cut [start, end] from input_video, reframe to 9:16 (1080x1920),
    burn ASS captions, and write to output_video.

    Uses input-side seeking (-ss before -i) for fast seeking, then
    re-encodes for frame-accurate output.
    """
    width, height = get_video_dimensions(input_video)
    crop_filter = _build_vertical_crop_filter(width, height)

    # ASS paths with backslashes or colons break FFmpeg's filter syntax on some
    # platforms. Use the escaped form: ass='path' (single-quoted, POSIX path).
    safe_ass = Path(ass_file).as_posix()
    vf = f"{crop_filter},ass='{safe_ass}'"

    cmd: list[str] = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-to", str(end),
        "-i", input_video,
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "128k",
        # Ensure output PTS starts from 0 (important for caption sync)
        "-avoid_negative_ts", "make_zero",
        output_video,
    ]
    run_cmd(cmd)
    return output_video


# ── ASS subtitle writer ───────────────────────────────────────────────────────

def _fmt_ass_time(t: float) -> str:
    """Format seconds as ASS timestamp H:MM:SS.cc"""
    t = max(0.0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def write_ass(subtitles: list[dict[str, Any]], ass_path: str) -> str:
    """
    Write an ASS subtitle file from a list of
    {"start": float, "end": float, "text": str} dicts.

    Times should be relative to the start of the clip (i.e. clip-start
    already subtracted), because the rendered clip's PTS begins at 0.
    """
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1080\n"
        "PlayResY: 1920\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        # White text, black outline, centre-bottom, large for mobile readability
        "Style: Default,Arial,72,&H00FFFFFF,&H00FFFFFF,&H00000000,"
        "&H64000000,-1,0,0,0,100,100,0,0,1,4,1,2,60,60,120,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    lines = [header]
    for item in subtitles:
        start_ts = _fmt_ass_time(float(item["start"]))
        end_ts = _fmt_ass_time(float(item["end"]))
        text = str(item["text"]).strip().replace("\n", "\\N")
        lines.append(f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,{text}\n")

    Path(ass_path).write_text("".join(lines), encoding="utf-8")
    return ass_path