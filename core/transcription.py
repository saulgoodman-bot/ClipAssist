"""What changed: Added optional pyannote diarization and transcript/diarization merge helpers."""
from __future__ import annotations

from typing import Any

from faster_whisper import WhisperModel

from core.config import PYANNOTE_TOKEN, WHISPER_MODEL_SIZE


def transcribe_word_timestamps(
    audio_path: str,
    model_size: str | None = None,
) -> dict[str, Any]:
    size = model_size or WHISPER_MODEL_SIZE
    model = WhisperModel(size)

    raw_segments, info = model.transcribe(audio_path, word_timestamps=True)

    output_segments: list[dict[str, Any]] = []
    full_text_parts: list[str] = []

    for segment in raw_segments:
        words = [
            {
                "start": word.start,
                "end": word.end,
                "word": word.word,
                "probability": word.probability,
            }
            for word in (segment.words or [])
        ]
        output_segments.append(
            {
                "start": segment.start,
                "end": segment.end,
                "text": segment.text.strip(),
                "words": words,
            }
        )
        full_text_parts.append(segment.text.strip())

    return {
        "language": info.language,
        "text": " ".join(full_text_parts),
        "segments": output_segments,
    }


def diarize_audio(audio_path: str) -> list[dict[str, Any]]:
    if not PYANNOTE_TOKEN:
        raise RuntimeError("PYANNOTE_TOKEN is required when diarization is enabled.")

    from pyannote.audio import Pipeline

    pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=PYANNOTE_TOKEN)
    diarization = pipeline(audio_path)

    turns: list[dict[str, Any]] = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        turns.append({"start": float(turn.start), "end": float(turn.end), "speaker": str(speaker)})
    return turns


def merge_diarization(segments: list[dict[str, Any]], diarization: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []

    for seg in segments:
        seg_start = float(seg["start"])
        seg_end = float(seg["end"])

        best_speaker = "unknown"
        best_overlap = 0.0

        for turn in diarization:
            overlap_start = max(seg_start, float(turn["start"]))
            overlap_end = min(seg_end, float(turn["end"]))
            overlap = max(0.0, overlap_end - overlap_start)
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = str(turn.get("speaker", "unknown"))

        with_speaker = dict(seg)
        with_speaker["speaker"] = best_speaker
        merged.append(with_speaker)

    return merged
