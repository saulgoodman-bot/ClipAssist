from __future__ import annotations

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from sqlmodel import Session, select

from api.schemas import ClipResponse, StatusResponse, UploadResponse
from db.models import Clip, Video
from db.session import get_session, init_db
from storage.file_manager import save_upload
from workers.tasks import process_video_pipeline

app = FastAPI(title="ClipAssist MVP")


@app.on_event("startup")
def startup() -> None:
    init_db()


def get_db() -> Session:
    with get_session() as session:
        yield session


@app.post("/upload", response_model=UploadResponse)
async def upload_video(file: UploadFile = File(...), session: Session = Depends(get_db)) -> UploadResponse:
    content = await file.read()
    if file.filename is None:
        raise HTTPException(status_code=400, detail="Invalid filename")
    saved_path = save_upload(content, file.filename)
    video = Video(filename=file.filename, s3_path=saved_path)
    session.add(video)
    session.commit()
    session.refresh(video)
    process_video_pipeline.delay(video.id)
    return UploadResponse(video_id=video.id, status=video.status.value)


@app.get("/status/{video_id}", response_model=StatusResponse)
def get_status(video_id: int, session: Session = Depends(get_db)) -> StatusResponse:
    video = session.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
    clip_rows = session.exec(select(Clip).where(Clip.video_id == video_id)).all()
    clips = [
        ClipResponse(
            id=c.id or 0,
            start_time=c.start_time,
            end_time=c.end_time,
            title=c.title,
            score=c.score,
            reason=c.reason,
            s3_path=c.s3_path,
        )
        for c in clip_rows
    ]
    return StatusResponse(
        video_id=video_id,
        status=video.status.value,
        progress_stage=video.progress_stage,
        clips=clips,
        error_message=video.error_message,
    )
