from __future__ import annotations

from typing import Any

from faster_whisper import WhisperModel

from core.config import WHISPER_MODEL_SIZE


def transcribe_word_timestamps(
    audio_path: str,
    model_size: str | None = None,
) -> dict[str, Any]:
    """
    Transcribe audio and return a dict with:
      {
        "language": str,
        "text": str,          # full transcript as plain text
        "segments": [         # sentence-level segments with timestamps
          {
            "start": float,
            "end": float,
            "text": str,
            "words": [{"start", "end", "word", "probability"}, ...]
          }
        ]
      }

    Note: transcribe() is a generator — we must exhaust it here before
    the WhisperModel goes out of scope, otherwise segments is empty.
    """
    size = model_size or WHISPER_MODEL_SIZE
    model = WhisperModel(size)

    raw_segments, info = model.transcribe(audio_path, word_timestamps=True)

    # Exhaust the generator before the model is released
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