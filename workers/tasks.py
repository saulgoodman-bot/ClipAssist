"""What changed: Added single-clip re-render task and clip status updates while preserving pipeline stages/logging."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from redis import Redis

from core.config import ENABLE_DIARIZATION, MAX_CLIPS, OUTPUT_DIR, REDIS_URL, TMP_DIR, WHISPER_MODEL_SIZE
from core.ingest import download_youtube
from core.intelligence import get_clip_segments
from core.media import extract_audio_wav, ffprobe_metadata, render_clip_with_ass, write_ass
from core.transcription import merge_transcript_with_diarization, diarize_audio, transcribe_word_timestamps
from db.models import Clip, Video, VideoStatus
from db.session import get_session
from storage.file_manager import cleanup_paths
from workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _log(video_id: int, progress_stage: str, message: str, **extra: object) -> None:
    payload = {"video_id": video_id, "progress_stage": progress_stage, **extra}
    logger.info("%s | %s", message, json.dumps(payload, default=str))


def _update_video(video_id: int, **kwargs: object) -> None:
    with get_session() as session:
        video = session.get(Video, video_id)
        if video is None:
            return
        for key, value in kwargs.items():
            setattr(video, key, value)
        session.add(video)
        session.commit()


def _publish_dead_letter(video_id: int, error: str) -> None:
    """Publish failed payload to dead-letter queue."""
    try:
        client = Redis.from_url(REDIS_URL, decode_responses=True)
        client.rpush(
            "clipassist:dead_letter",
            json.dumps({"video_id": video_id, "error": error, "timestamp": datetime.now(timezone.utc).isoformat()}),
        )
    except Exception:
        logger.exception("dead-letter publish failed")


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def process_video_pipeline(self, video_id: int, stage: str = "start") -> None:  # noqa: ANN001
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with get_session() as session:
        video = session.get(Video, video_id)
        if video is None:
            return
        video_path = video.s3_path
        video.status = VideoStatus.PROCESSING
        video.progress_stage = "metadata"
        session.add(video)
        session.commit()

    wav_path = str(TMP_DIR / f"{video_id}.wav")
    transcript: dict = {"segments": []}
    try:
        metadata = ffprobe_metadata(video_path)
        _update_video(video_id, duration=float(metadata.get("format", {}).get("duration", 0.0)), progress_stage="extracting_audio")
        extract_audio_wav(video_path, wav_path)

        _update_video(video_id, progress_stage="transcribing")
        transcript = transcribe_word_timestamps(wav_path, model_size=WHISPER_MODEL_SIZE)
        (TMP_DIR / f"{video_id}_transcript.json").write_text(json.dumps(transcript, ensure_ascii=False), encoding="utf-8")

        if ENABLE_DIARIZATION:
            try:
                transcript["segments"] = merge_transcript_with_diarization(transcript["segments"], diarize_audio(wav_path))
            except Exception as exc:
                _log(video_id, "diarizing", "diarization failed; continuing", error=str(exc))

        _update_video(video_id, progress_stage="analyzing")
        selected_clips = get_clip_segments(transcript["segments"])

        _update_video(video_id, progress_stage="rendering")
        for idx, seg in enumerate(selected_clips[:MAX_CLIPS], start=1):
            stage = "rendering"
            start = float(seg["start"])
            end = float(seg["end"])
            subtitle_items = [
                {"start": s["start"] - start, "end": s["end"] - start, "text": s["text"].strip()}
                for s in transcript["segments"]
                if s["start"] >= start and s["end"] <= end and s["text"].strip()
            ]
            clip_ass = str(TMP_DIR / f"{video_id}_{idx}.ass")
            write_ass(subtitle_items, clip_ass)
            local_output_path = str(OUTPUT_DIR / f"video_{video_id}_clip_{idx}.mp4")
            render_clip_with_ass(video_path, local_output_path, clip_ass, start, end)
            output_key = local_output_path

            with get_session() as session:
                session.add(
                    Clip(
                        video_id=video_id,
                        start_time=start,
                        end_time=end,
                        title=str(seg.get("title", f"Clip {idx}")),
                        score=float(seg.get("score", 0.0)),
                        reason=str(seg.get("reason", "")),
                        s3_path=output_key,
                        status="completed",
                    )
                )
                session.commit()
            cleanup_paths(clip_ass)

        cleanup_paths(wav_path)
        _update_video(video_id, status=VideoStatus.COMPLETED, progress_stage="completed")
    except Exception as exc:
        _update_video(video_id, status=VideoStatus.FAILED, error_message=str(exc)[:1000])
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            _publish_dead_letter(video_id, str(exc))


@celery_app.task(bind=True, max_retries=1, default_retry_delay=15)
def ingest_youtube_video(self, video_id: int, url: str) -> None:  # noqa: ANN001
    try:
        _update_video(video_id, status=VideoStatus.PROCESSING, progress_stage="ingest_youtube")
        downloaded_path = download_youtube(url, str(TMP_DIR))
        persisted_key = downloaded_path
        _update_video(video_id, s3_path=persisted_key, progress_stage="queued_for_processing")
        process_video_pipeline.delay(video_id)
    except Exception as exc:
        _update_video(video_id, status=VideoStatus.FAILED, error_message=str(exc)[:1000])
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            _publish_dead_letter(video_id, str(exc))


@celery_app.task(bind=True, max_retries=1, default_retry_delay=15)
def render_single_clip(self, clip_id: int) -> None:  # noqa: ANN001
    with get_session() as session:
        clip = session.get(Clip, clip_id)
        if clip is None:
            return
        video = session.get(Video, clip.video_id)
        if video is None:
            clip.status = "failed"
            session.add(clip)
            session.commit()
            return
        clip.status = "rendering"
        session.add(clip)
        session.commit()
        video_path = video.s3_path

    try:
        start, end = float(clip.start_time), float(clip.end_time)
        ass_path = str(TMP_DIR / f"rerender_{clip_id}.ass")
        write_ass([], ass_path)
        local_output_path = str(OUTPUT_DIR / f"clip_{clip_id}_rerender.mp4")
        render_clip_with_ass(video_path, local_output_path, ass_path, start, end)
        key = local_output_path
        cleanup_paths(ass_path)
        with get_session() as session:
            db_clip = session.get(Clip, clip_id)
            if db_clip:
                db_clip.s3_path = key
                db_clip.status = "ready"
                session.add(db_clip)
                session.commit()
    except Exception:
        with get_session() as session:
            db_clip = session.get(Clip, clip_id)
            if db_clip:
                db_clip.status = "failed"
                session.add(db_clip)
                session.commit()
        raise
