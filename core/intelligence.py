from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

SYSTEM_PROMPT = (
    "You are an expert social media editor. Analyze this transcript. "
    "Identify the top 5 most engaging moments between 30-60 seconds. "
    "Each must have a strong 'hook' in the first 5 seconds. "
    "Return a JSON array of objects: "
    '{"start": float, "end": float, "title": str, "score": float, "reason": str}.'
)


def get_clip_segments(transcript_text: str, model: str = "gpt-4.1-mini", max_retries: int = 3) -> list[dict[str, Any]]:
    client = OpenAI()
    for _ in range(max_retries):
        response = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": transcript_text},
            ],
        )
        content = response.output_text
        try:
            parsed = json.loads(content)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            continue
    raise ValueError("LLM failed to return valid JSON after retries")
