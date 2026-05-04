from __future__ import annotations

from typing import Any

from faster_whisper import WhisperModel


def transcribe_word_timestamps(audio_path: str, model_size: str = "base") -> dict[str, Any]:
    model = WhisperModel(model_size)
    segments, info = model.transcribe(audio_path, word_timestamps=True)
    output_segments: list[dict[str, Any]] = []
    full_text_parts: list[str] = []
    for segment in segments:
        words = []
        for word in segment.words or []:
            words.append({"start": word.start, "end": word.end, "word": word.word, "probability": word.probability})
        output_segments.append({"start": segment.start, "end": segment.end, "text": segment.text, "words": words})
        full_text_parts.append(segment.text.strip())
    return {"language": info.language, "text": " ".join(full_text_parts), "segments": output_segments}
