from __future__ import annotations

import json
from pathlib import Path

from sqlmodel import select

from core.intelligence import get_clip_segments
from core.media import extract_audio_wav, ffprobe_metadata, render_clip_with_ass, write_ass
from core.transcription import transcribe_word_timestamps
from db.models import Clip, Video, VideoStatus
from db.session import get_session
from storage.file_manager import OUTPUT_DIR, TMP_DIR, cleanup_paths
from workers.celery_app import celery_app


@celery_app.task
def process_video_pipeline(video_id: int) -> None:
    with get_session() as session:
        video = session.get(Video, video_id)
        if video is None:
            return
        try:
            video.status = VideoStatus.PROCESSING
            video.progress_stage = "metadata"
            session.add(video)
            session.commit()

            metadata = ffprobe_metadata(video.s3_path)
            duration = float(metadata.get("format", {}).get("duration", 0.0))
            video.duration = duration

            video.progress_stage = "transcribing"
            session.add(video)
            session.commit()

            TMP_DIR.mkdir(parents=True, exist_ok=True)
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            wav_path = str(TMP_DIR / f"{video_id}.wav")
            extract_audio_wav(video.s3_path, wav_path)
            transcript = transcribe_word_timestamps(wav_path, model_size="base")

            video.progress_stage = "analyzing"
            session.add(video)
            session.commit()

            segments = get_clip_segments(transcript["text"])

            video.progress_stage = "rendering"
            session.add(video)
            session.commit()

            for idx, seg in enumerate(segments[:5], start=1):
                start = float(seg["start"])
                end = float(seg["end"])
                clip_ass = str(TMP_DIR / f"{video_id}_{idx}.ass")
                subtitle_items = [
                    {"start": s["start"] - start, "end": s["end"] - start, "text": s["text"]}
                    for s in transcript["segments"] if s["start"] >= start and s["end"] <= end
                ]
                write_ass(subtitle_items, clip_ass)
                output_path = str(OUTPUT_DIR / f"video_{video_id}_clip_{idx}.mp4")
                render_clip_with_ass(video.s3_path, output_path, clip_ass, start, end)
                clip = Clip(
                    video_id=video_id,
                    start_time=start,
                    end_time=end,
                    title=str(seg["title"]),
                    score=float(seg["score"]),
                    reason=str(seg["reason"]),
                    s3_path=output_path,
                )
                session.add(clip)
                cleanup_paths(clip_ass)

            cleanup_paths(wav_path)
            transcript_path = TMP_DIR / f"{video_id}_transcript.json"
            transcript_path.write_text(json.dumps(transcript), encoding="utf-8")
            video.status = VideoStatus.COMPLETED
            video.progress_stage = "completed"
            session.add(video)
            session.commit()
        except Exception as exc:
            video.status = VideoStatus.FAILED
            video.error_message = str(exc)
            session.add(video)
            session.commit()
            raise
