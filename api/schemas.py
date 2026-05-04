from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class UploadResponse(BaseModel):
    video_id: int
    status: str


class ClipResponse(BaseModel):
    id: int
    start_time: float
    end_time: float
    title: str
    score: float
    reason: str
    s3_path: str


class StatusResponse(BaseModel):
    video_id: int
    status: str
    progress_stage: Optional[str]
    clips: list[ClipResponse]
    error_message: Optional[str]
