from __future__ import annotations

import json
from pathlib import Path

from core.config import MAX_CLIPS, OUTPUT_DIR, TMP_DIR, WHISPER_MODEL_SIZE
from core.intelligence import get_clip_segments
from core.media import (
    extract_audio_wav,
    ffprobe_metadata,
    render_clip_with_ass,
    write_ass,
)
from core.transcription import transcribe_word_timestamps
from db.models import Clip, Video, VideoStatus
from db.session import get_session
from storage.file_manager import cleanup_paths
from workers.celery_app import celery_app


def _update_video(video_id: int, **kwargs: object) -> None:
    """Helper: open a session, update Video fields, commit, close."""
    with get_session() as session:
        video = session.get(Video, video_id)
        if video is None:
            return
        for key, value in kwargs.items():
            setattr(video, key, value)
        session.add(video)
        session.commit()


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def process_video_pipeline(self, video_id: int) -> None:  # noqa: ANN001
    """
    Full pipeline:
      metadata → audio extraction → transcription →
      clip selection → rendering → done
    """
    # Ensure working directories exist
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── 1. Load video record ──────────────────────────────────────────────────
    with get_session() as session:
        video = session.get(Video, video_id)
        if video is None:
            print(f"[task] Video {video_id} not found — aborting.")
            return
        video_path = video.s3_path  # local path for now (no S3 yet)
        video.status = VideoStatus.PROCESSING
        video.progress_stage = "metadata"
        session.add(video)
        session.commit()

    try:
        # ── 2. Probe metadata ─────────────────────────────────────────────────
        metadata = ffprobe_metadata(video_path)
        duration = float(metadata.get("format", {}).get("duration", 0.0))
        _update_video(video_id, duration=duration)

        # ── 3. Extract audio ──────────────────────────────────────────────────
        _update_video(video_id, progress_stage="extracting_audio")
        wav_path = str(TMP_DIR / f"{video_id}.wav")
        extract_audio_wav(video_path, wav_path)

        # ── 4. Transcribe ─────────────────────────────────────────────────────
        _update_video(video_id, progress_stage="transcribing")
        transcript = transcribe_word_timestamps(wav_path, model_size=WHISPER_MODEL_SIZE)

        # Persist transcript for debugging / future use
        transcript_path = TMP_DIR / f"{video_id}_transcript.json"
        transcript_path.write_text(json.dumps(transcript, ensure_ascii=False), encoding="utf-8")

        # ── 5. Clip selection via LLM ─────────────────────────────────────────
        # BUG FIX: pass transcript["segments"] (with start/end timestamps),
        # NOT transcript["text"] (plain prose with no timestamp information).
        # The LLM needs real timestamps to return valid clip windows.
        _update_video(video_id, progress_stage="analyzing")
        selected_clips = get_clip_segments(transcript["segments"])

        # ── 6. Render each clip ───────────────────────────────────────────────
        _update_video(video_id, progress_stage="rendering")
        for idx, seg in enumerate(selected_clips[:MAX_CLIPS], start=1):
            start = float(seg["start"])
            end = float(seg["end"])

            # Build ASS captions: filter transcript segments that fall within
            # this clip window and offset timestamps to be clip-relative (→ 0-based).
            subtitle_items = [
                {
                    "start": s["start"] - start,
                    "end": s["end"] - start,
                    "text": s["text"].strip(),
                }
                for s in transcript["segments"]
                if s["start"] >= start and s["end"] <= end and s["text"].strip()
            ]

            clip_ass = str(TMP_DIR / f"{video_id}_{idx}.ass")
            write_ass(subtitle_items, clip_ass)

            output_path = str(OUTPUT_DIR / f"video_{video_id}_clip_{idx}.mp4")
            render_clip_with_ass(video_path, output_path, clip_ass, start, end)

            # Persist clip record
            with get_session() as session:
                clip = Clip(
                    video_id=video_id,
                    start_time=start,
                    end_time=end,
                    title=str(seg.get("title", f"Clip {idx}")),
                    score=float(seg.get("score", 0.0)),
                    reason=str(seg.get("reason", "")),
                    s3_path=output_path,
                )
                session.add(clip)
                session.commit()

            cleanup_paths(clip_ass)

        # ── 7. Clean up and mark complete ─────────────────────────────────────
        cleanup_paths(wav_path)
        _update_video(video_id, status=VideoStatus.COMPLETED, progress_stage="completed")
        print(f"[task] Video {video_id} — pipeline complete.")

    except Exception as exc:
        print(f"[task] Video {video_id} — pipeline FAILED: {exc}")
        _update_video(video_id, status=VideoStatus.FAILED, error_message=str(exc)[:1000])
        # Celery retry (up to max_retries defined on the task decorator)
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            pass  # Already marked FAILED above