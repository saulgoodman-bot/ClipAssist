"""What changed: Added User model, video ownership, and clip edit/render state fields for API auth and editing."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column, DateTime, String
from sqlmodel import Field, SQLModel


class VideoStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DELETED = "deleted"


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(sa_column=Column(String, unique=True, index=True, nullable=False))
    hashed_password: str
    plan: str = Field(default="free")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Video(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    filename: str
    s3_path: str
    user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    duration: Optional[float] = None
    status: VideoStatus = Field(default=VideoStatus.PENDING)
    progress_stage: Optional[str] = None
    error_message: Optional[str] = None
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow),
    )


class Clip(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    video_id: int = Field(index=True, foreign_key="video.id")
    start_time: float
    end_time: float
    title: str
    score: float
    reason: str
    s3_path: str
    status: str = Field(default="completed")
    layout_mode: Optional[str] = None
