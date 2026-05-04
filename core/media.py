from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


def run_cmd(command: list[str]) -> None:
    subprocess.run(command, check=True)


def ffprobe_metadata(video_path: str) -> dict[str, Any]:
    cmd: list[str] = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        video_path,
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def extract_audio_wav(video_path: str, wav_path: str) -> str:
    cmd: list[str] = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav_path,
    ]
    run_cmd(cmd)
    return wav_path


def render_clip_with_ass(input_video: str, output_video: str, ass_file: str, start: float, end: float) -> str:
    vf = "scale=1080:-2,crop=1080:1920,ass={}".format(ass_file)
    cmd: list[str] = [
        "ffmpeg", "-y", "-ss", str(start), "-to", str(end), "-i", input_video,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-b:a", "128k",
        output_video,
    ]
    run_cmd(cmd)
    return output_video


def write_ass(subtitles: list[dict[str, float | str]], ass_path: str) -> str:
    header = """[Script Info]
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,3,2,1,2,30,30,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def fmt(t: float) -> str:
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = t % 60
        return f"{h}:{m:02d}:{s:05.2f}"

    lines = [header]
    for item in subtitles:
        lines.append(f"Dialogue: 0,{fmt(float(item['start']))},{fmt(float(item['end']))},Default,,0,0,0,,{item['text']}\n")
    Path(ass_path).write_text("".join(lines), encoding="utf-8")
    return ass_path
