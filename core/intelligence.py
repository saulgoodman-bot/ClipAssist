from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from core.config import MAX_CLIP_SECONDS, MAX_CLIPS, MIN_CLIP_SECONDS, OPENAI_API_KEY, OPENAI_MODEL

# ── Prompt ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = f"""You are an expert short-form video editor.

You will receive a JSON array of transcript segments, each with "start" (seconds),
"end" (seconds), and "text" fields.

Your task: identify the {MAX_CLIPS} best moments for short-form social clips
(YouTube Shorts, TikTok, Instagram Reels).

Rules for a good clip:
- Between {MIN_CLIP_SECONDS} and {MAX_CLIP_SECONDS} seconds long.
- Opens with a strong hook in the first 3 seconds.
- Stands alone without needing prior context.
- Contains a complete idea, story, insight, opinion, or emotional moment.
- Does not start or end mid-sentence.
- You may span multiple consecutive segments to form one clip.

Score each candidate clip (0-10) on:
  hook_strength, clarity, emotional_intensity, standalone_value, viral_potential

Return ONLY valid JSON in this exact schema — no prose, no markdown fences:

{{
  "clips": [
    {{
      "start": <float seconds>,
      "end": <float seconds>,
      "title": "<catchy title under 60 chars>",
      "hook": "<first sentence / hook text>",
      "summary": "<1-2 sentence description>",
      "score": <float 0-10>,
      "reason": "<why this clip works>",
      "hashtags": ["#tag1", "#tag2"]
    }}
  ]
}}
"""


def get_clip_segments(
    segments: list[dict[str, Any]],
    model: str | None = None,
    max_retries: int = 3,
) -> list[dict[str, Any]]:
    """
    Args:
        segments: List of dicts with keys 'start', 'end', 'text' from the transcript.
                  These must include real timestamps so the LLM can return valid clip windows.
        model: Override the model from config.
        max_retries: Number of LLM call retries on JSON parse failure.

    Returns:
        List of clip dicts matching the schema above.

    Raises:
        ValueError: If valid JSON cannot be parsed after all retries.
    """
    client = OpenAI(api_key=OPENAI_API_KEY)
    chosen_model = model or OPENAI_MODEL

    # Only send the fields the LLM needs (keep the prompt compact).
    slim_segments = [
        {"start": round(s["start"], 2), "end": round(s["end"], 2), "text": s["text"]}
        for s in segments
    ]
    user_content = json.dumps(slim_segments, ensure_ascii=False)

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=chosen_model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.3,  # Lower temp = more consistent JSON structure
            )
            content = response.choices[0].message.content or ""
            parsed: Any = json.loads(content)

            # Accept either {"clips": [...]} or a bare list
            if isinstance(parsed, dict) and "clips" in parsed:
                clips = parsed["clips"]
            elif isinstance(parsed, list):
                clips = parsed
            else:
                raise ValueError(f"Unexpected JSON shape: {type(parsed)}")

            # Basic validation: each clip must have start, end, title, score
            for clip in clips:
                for key in ("start", "end", "title", "score"):
                    if key not in clip:
                        raise ValueError(f"Clip missing required key '{key}': {clip}")

            return clips

        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            last_error = exc
            print(f"[intelligence] attempt {attempt}/{max_retries} failed: {exc}")

    raise ValueError(
        f"LLM failed to return valid clip JSON after {max_retries} retries. "
        f"Last error: {last_error}"
    )