from __future__ import annotations

from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


class VideoStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Video(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    filename: str
    s3_path: str
    duration: Optional[float] = None
    status: VideoStatus = Field(default=VideoStatus.PENDING)
    progress_stage: Optional[str] = None
    error_message: Optional[str] = None


class Clip(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    video_id: int = Field(index=True, foreign_key="video.id")
    start_time: float
    end_time: float
    title: str
    score: float
    reason: str
    s3_path: str
