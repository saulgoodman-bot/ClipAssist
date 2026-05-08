# pip install pyannote.audio
"""Audio transcription and optional speaker diarization helpers."""
from __future__ import annotations

import os
from typing import Any

from faster_whisper import WhisperModel

from core.config import WHISPER_MODEL_SIZE


def diarize_audio(audio_path: str) -> list[dict[str, Any]]:
    """Run speaker diarization and return speaker windows."""
    token = os.getenv("HF_TOKEN")
    if not token:
        return []

    from pyannote.audio import Pipeline

    pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=token)
    diarization = pipeline(audio_path)
    windows: list[dict[str, Any]] = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        windows.append({"start": float(turn.start), "end": float(turn.end), "speaker": str(speaker)})
    return windows


def merge_transcript_with_diarization(segments: list[dict[str, Any]], diarization: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge transcript segments with speaker labels by max overlap."""
    merged: list[dict[str, Any]] = []
    for segment in segments:
        seg_start = float(segment.get("start", 0.0))
        seg_end = float(segment.get("end", 0.0))
        best_speaker = "SPEAKER_00"
        best_overlap = 0.0

        for window in diarization:
            overlap_start = max(seg_start, float(window.get("start", 0.0)))
            overlap_end = min(seg_end, float(window.get("end", 0.0)))
            overlap = max(0.0, overlap_end - overlap_start)
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = str(window.get("speaker", "SPEAKER_00"))

        enriched = dict(segment)
        enriched["speaker"] = best_speaker
        merged.append(enriched)
    return merged


def transcribe_word_timestamps(audio_path: str, model_size: str | None = None, diarize: bool = False) -> dict[str, Any]:
    """Transcribe audio with word timestamps and optional speaker labels."""
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
        output_segments.append({"start": segment.start, "end": segment.end, "text": segment.text.strip(), "words": words})
        full_text_parts.append(segment.text.strip())

    if diarize:
        output_segments = merge_transcript_with_diarization(output_segments, diarize_audio(audio_path))

    return {"language": info.language, "text": " ".join(full_text_parts), "segments": output_segments}
