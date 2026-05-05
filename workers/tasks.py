"""What changed: Added structured stage logging, optional diarization, S3 output persistence, YouTube ingest task, and dead-letter publishing."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import redis

from core.config import ENABLE_DIARIZATION, MAX_CLIPS, OUTPUT_DIR, REDIS_URL, TMP_DIR, WHISPER_MODEL_SIZE
from core.ingest import download_youtube
from core.intelligence import get_clip_segments
from core.media import extract_audio_wav, ffprobe_metadata, render_clip_with_ass, write_ass
from core.transcription import diarize_audio, merge_diarization, transcribe_word_timestamps
from db.models import Clip, Video, VideoStatus
from db.session import get_session
from storage.file_manager import cleanup_keys, save_output
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
    try:
        client = redis.from_url(REDIS_URL, decode_responses=True)
        message = {
            "video_id": video_id,
            "error": error,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        client.rpush("clipassist:dead_letter", json.dumps(message))
    except Exception:
        logger.exception("dead-letter publish failed", extra={"video_id": video_id, "progress_stage": "dead_letter"})


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def process_video_pipeline(self, video_id: int) -> None:  # noqa: ANN001
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with get_session() as session:
        video = session.get(Video, video_id)
        if video is None:
            logger.error("video not found", extra={"video_id": video_id, "progress_stage": "load"})
            return
        video_path = video.s3_path
        video.status = VideoStatus.PROCESSING
        video.progress_stage = "metadata"
        session.add(video)
        session.commit()

    wav_path = str(TMP_DIR / f"{video_id}.wav")
    transcript: dict = {"segments": []}
    selected_clips: list[dict] = []

    try:
        try:
            _update_video(video_id, progress_stage="metadata")
            metadata = ffprobe_metadata(video_path)
            duration = float(metadata.get("format", {}).get("duration", 0.0))
            _update_video(video_id, duration=duration)
            _log(video_id, "metadata", "metadata complete", duration=duration)
        except Exception as exc:
            _log(video_id, "metadata", "metadata failed", error=str(exc))
            raise

        try:
            _update_video(video_id, progress_stage="extracting_audio")
            extract_audio_wav(video_path, wav_path)
            _log(video_id, "extracting_audio", "audio extracted", wav_path=wav_path)
        except Exception as exc:
            _log(video_id, "extracting_audio", "audio extraction failed", error=str(exc))
            raise

        try:
            _update_video(video_id, progress_stage="transcribing")
            transcript = transcribe_word_timestamps(wav_path, model_size=WHISPER_MODEL_SIZE)
            transcript_path = TMP_DIR / f"{video_id}_transcript.json"
            transcript_path.write_text(json.dumps(transcript, ensure_ascii=False), encoding="utf-8")
            _log(video_id, "transcribing", "transcription complete", transcript_path=str(transcript_path))
        except Exception as exc:
            _log(video_id, "transcribing", "transcription failed", error=str(exc))
            raise

        if ENABLE_DIARIZATION:
            try:
                _update_video(video_id, progress_stage="diarizing")
                diarization = diarize_audio(wav_path)
                transcript["segments"] = merge_diarization(transcript["segments"], diarization)
                _log(video_id, "diarizing", "diarization complete", diarization_turns=len(diarization))
            except Exception as exc:
                _log(video_id, "diarizing", "diarization failed; continuing without speaker labels", error=str(exc))

        try:
            _update_video(video_id, progress_stage="analyzing")
            selected_clips = get_clip_segments(transcript["segments"])
            _log(video_id, "analyzing", "clip selection complete", clips=len(selected_clips))
        except Exception as exc:
            _log(video_id, "analyzing", "clip selection failed", error=str(exc))
            raise

        _update_video(video_id, progress_stage="rendering")
        for idx, seg in enumerate(selected_clips[:MAX_CLIPS], start=1):
            stage = "rendering"
            start = float(seg["start"])
            end = float(seg["end"])
            try:
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

                local_output_path = str(OUTPUT_DIR / f"video_{video_id}_clip_{idx}.mp4")
                render_clip_with_ass(video_path, local_output_path, clip_ass, start, end)
                output_key = save_output(local_output_path, f"outputs/video_{video_id}_clip_{idx}.mp4")

                with get_session() as session:
                    clip = Clip(
                        video_id=video_id,
                        start_time=start,
                        end_time=end,
                        title=str(seg.get("title", f"Clip {idx}")),
                        score=float(seg.get("score", 0.0)),
                        reason=str(seg.get("reason", "")),
                        s3_path=output_key,
                    )
                    session.add(clip)
                    session.commit()

                cleanup_keys(clip_ass)
                _log(video_id, stage, "clip rendered", clip_index=idx, output_key=output_key)
            except Exception as exc:
                _log(video_id, stage, "clip render failed; continuing", clip_index=idx, error=str(exc))

        cleanup_keys(wav_path)
        _update_video(video_id, status=VideoStatus.COMPLETED, progress_stage="completed")
        _log(video_id, "completed", "pipeline complete")

    except Exception as exc:
        _update_video(video_id, status=VideoStatus.FAILED, error_message=str(exc)[:1000])
        _log(video_id, "failed", "pipeline failed", error=str(exc))
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            _publish_dead_letter(video_id, str(exc))


@celery_app.task(bind=True, max_retries=1, default_retry_delay=15)
def ingest_youtube_video(self, video_id: int, url: str) -> None:  # noqa: ANN001
    stage = "ingest_youtube"
    try:
        _update_video(video_id, status=VideoStatus.PROCESSING, progress_stage=stage)
        downloaded_path = download_youtube(url, str(TMP_DIR))
        persisted_key = save_output(downloaded_path, f"uploads/video_{video_id}.mp4")
        _update_video(video_id, s3_path=persisted_key, progress_stage="queued_for_processing")
        _log(video_id, stage, "youtube ingest complete", url=url, persisted_key=persisted_key)
        process_video_pipeline.delay(video_id)
    except Exception as exc:
        _update_video(video_id, status=VideoStatus.FAILED, error_message=str(exc)[:1000])
        _log(video_id, stage, "youtube ingest failed", error=str(exc))
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            _publish_dead_letter(video_id, str(exc))
