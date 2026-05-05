"""What changed: Added JWT auth routes, protected video/clip APIs, transcript/delete/edit/render/download endpoints, and upload guards."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

import boto3
import redis
from botocore.exceptions import ClientError
from fastapi import Depends, FastAPI, File, Header, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from sqlmodel import Session, select

from api.auth import create_access_token, get_current_user, hash_password, verify_password
from api.schemas import (
    AuthResponse,
    ClipResponse,
    ClipUpdateRequest,
    IngestUrlRequest,
    LoginRequest,
    MeResponse,
    RegisterRequest,
    RenderResponse,
    StatusResponse,
    TranscriptResponse,
    UploadResponse,
)
from core.config import (
    MAX_DAILY_UPLOADS,
    MAX_UPLOAD_MB,
    REDIS_URL,
    S3_BUCKET,
    S3_ENDPOINT_URL,
    STORAGE_BACKEND,
    TMP_DIR,
)
from db.models import Clip, User, Video, VideoStatus
from db.session import get_session, init_db
from storage.file_manager import cleanup_keys, get_presigned_url, save_upload
from workers.tasks import ingest_youtube_video, process_video_pipeline, render_single_clip

app = FastAPI(title="ClipAssist MVP")
rate_redis = redis.from_url(REDIS_URL, decode_responses=True)
YOUTUBE_URL_RE = re.compile(r"^(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/)", re.IGNORECASE)


@app.on_event("startup")
def startup() -> None:
    init_db()


def get_db() -> Generator[Session, None, None]:
    with get_session() as session:
        yield session


def _check_rate_limit(user_id: int) -> None:
    day_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = f"ratelimit:uploads:{user_id}:{day_key}"
    count = rate_redis.incr(key)
    if count == 1:
        rate_redis.expire(key, 86400)
    if count > MAX_DAILY_UPLOADS:
        raise HTTPException(status_code=429, detail="Daily upload limit exceeded")


def _ensure_video_owner(video: Video | None, user: User) -> Video:
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
    if video.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized for this video")
    return video


def _ensure_clip_owner(session: Session, clip_id: int, user: User) -> tuple[Clip, Video]:
    clip = session.get(Clip, clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="Clip not found")
    video = session.get(Video, clip.video_id)
    _ensure_video_owner(video, user)
    return clip, video


@app.post("/auth/register", response_model=AuthResponse)
def register(payload: RegisterRequest, session: Session = Depends(get_db)) -> AuthResponse:
    existing = session.exec(select(User).where(User.email == payload.email)).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(email=payload.email, hashed_password=hash_password(payload.password))
    session.add(user)
    session.commit()
    session.refresh(user)
    token = create_access_token(user.id or 0, user.email)
    return AuthResponse(user_id=user.id or 0, email=user.email, access_token=token)


@app.post("/auth/login", response_model=AuthResponse)
def login(payload: LoginRequest, session: Session = Depends(get_db)) -> AuthResponse:
    user = session.exec(select(User).where(User.email == payload.email)).first()
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_access_token(user.id or 0, user.email)
    return AuthResponse(user_id=user.id or 0, email=user.email, access_token=token)


@app.get("/auth/me", response_model=MeResponse)
def me(current_user: User = Depends(get_current_user)) -> MeResponse:
    return MeResponse(user_id=current_user.id or 0, email=current_user.email, plan=current_user.plan)


@app.post("/upload", response_model=UploadResponse)
async def upload_video(
    file: UploadFile = File(...),
    content_length: int | None = Header(default=None, alias="Content-Length"),
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UploadResponse:
    _check_rate_limit(current_user.id or 0)
    max_bytes = MAX_UPLOAD_MB * 1024 * 1024
    if content_length is not None and content_length > max_bytes:
        raise HTTPException(status_code=413, detail=f"File too large. Max {MAX_UPLOAD_MB}MB")

    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required.")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File too large. Max {MAX_UPLOAD_MB}MB")

    saved_path = save_upload(content, file.filename)

    video = Video(filename=file.filename, s3_path=saved_path, user_id=current_user.id)
    session.add(video)
    session.commit()
    session.refresh(video)

    process_video_pipeline.delay(video.id)
    return UploadResponse(video_id=video.id or 0, status=video.status.value)


@app.post("/videos/ingest-url", response_model=UploadResponse)
def ingest_url(
    payload: IngestUrlRequest,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UploadResponse:
    _check_rate_limit(current_user.id or 0)
    if not YOUTUBE_URL_RE.match(payload.url.strip()):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")

    video = Video(
        filename=payload.url.strip().split("v=")[-1][:64],
        s3_path="",
        status=VideoStatus.PENDING,
        user_id=current_user.id,
    )
    session.add(video)
    session.commit()
    session.refresh(video)

    ingest_youtube_video.delay(video.id, payload.url.strip())
    return UploadResponse(video_id=video.id or 0, status=video.status.value)


@app.get("/status/{video_id}", response_model=StatusResponse)
def get_status(video_id: int, session: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> StatusResponse:
    video = _ensure_video_owner(session.get(Video, video_id), current_user)
    clip_rows = session.exec(select(Clip).where(Clip.video_id == video_id)).all()
    clips = [ClipResponse.model_validate(c) for c in clip_rows]
    return StatusResponse(
        video_id=video_id,
        status=video.status.value,
        progress_stage=video.progress_stage,
        duration=video.duration,
        clips=clips,
        error_message=video.error_message,
    )


@app.get("/videos/{video_id}/transcript", response_model=TranscriptResponse)
def get_transcript(video_id: int, session: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> TranscriptResponse:
    _ensure_video_owner(session.get(Video, video_id), current_user)

    transcript_path = TMP_DIR / f"{video_id}_transcript.json"
    content: dict
    if STORAGE_BACKEND == "s3":
        key = f"tmp/{video_id}_transcript.json"
        try:
            obj = boto3.client("s3", endpoint_url=S3_ENDPOINT_URL or None).get_object(Bucket=S3_BUCKET, Key=key)
            content = json.loads(obj["Body"].read().decode("utf-8"))
        except Exception:
            raise HTTPException(status_code=404, detail="Transcript not found")
    else:
        if not transcript_path.exists():
            raise HTTPException(status_code=404, detail="Transcript not found")
        content = json.loads(transcript_path.read_text(encoding="utf-8"))

    segments = [
        {"start": s["start"], "end": s["end"], "speaker": s.get("speaker"), "text": s.get("text", "")}
        for s in content.get("segments", [])
    ]
    return TranscriptResponse(video_id=video_id, language=content.get("language", ""), full_text=content.get("text", ""), segments=segments)


@app.delete("/videos/{video_id}", status_code=204)
def delete_video(video_id: int, session: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> Response:
    video = _ensure_video_owner(session.get(Video, video_id), current_user)
    clips = session.exec(select(Clip).where(Clip.video_id == video_id)).all()

    cleanup_keys(video.s3_path, *[c.s3_path for c in clips])
    video.status = VideoStatus.DELETED
    session.add(video)
    session.commit()
    return Response(status_code=204)


@app.patch("/clips/{clip_id}", response_model=ClipResponse)
def patch_clip(clip_id: int, payload: ClipUpdateRequest, session: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> ClipResponse:
    clip, _ = _ensure_clip_owner(session, clip_id, current_user)

    if payload.start_time is not None:
        clip.start_time = payload.start_time
    if payload.end_time is not None:
        clip.end_time = payload.end_time
    if payload.title is not None:
        clip.title = payload.title
    if payload.layout_mode is not None:
        clip.layout_mode = payload.layout_mode

    duration = clip.end_time - clip.start_time
    if duration < 10 or duration > 120:
        raise HTTPException(status_code=422, detail="clip duration must be between 10 and 120 seconds")

    clip.status = "edited"
    session.add(clip)
    session.commit()
    session.refresh(clip)
    return ClipResponse.model_validate(clip)


@app.post("/clips/{clip_id}/render", response_model=RenderResponse)
def render_clip(clip_id: int, session: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> RenderResponse:
    clip, _ = _ensure_clip_owner(session, clip_id, current_user)
    clip.status = "rendering"
    session.add(clip)
    session.commit()
    render_single_clip.delay(clip_id)
    return RenderResponse(clip_id=clip_id, status="rendering")


@app.get("/clips/{clip_id}/download")
def download_clip(clip_id: int, session: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    clip, _ = _ensure_clip_owner(session, clip_id, current_user)
    if clip.status not in {"ready", "completed"}:
        raise HTTPException(status_code=409, detail="Clip is not ready")

    if STORAGE_BACKEND == "s3":
        try:
            boto3.client("s3", endpoint_url=S3_ENDPOINT_URL or None).head_object(Bucket=S3_BUCKET, Key=clip.s3_path)
        except ClientError:
            raise HTTPException(status_code=404, detail="Clip file not found")
        return RedirectResponse(get_presigned_url(clip.s3_path), status_code=302)

    clip_path = Path(clip.s3_path)
    if not clip_path.exists():
        raise HTTPException(status_code=404, detail="Clip file not found")
    return FileResponse(str(clip_path), media_type="video/mp4", filename=f"clip_{clip_id}.mp4")
