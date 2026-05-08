"""What changed: Added auth, transcript, clip edit/render, ingest URL, and expanded status schemas using Pydantic v2 config."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class RegisterRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)


class LoginRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: int
    email: str
    access_token: str


class MeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: int
    email: str
    plan: str


class UploadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    video_id: int
    status: str


class TranscriptSegment(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    start: float
    end: float
    speaker: Optional[str] = None
    text: str


class TranscriptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    video_id: int
    language: str
    segments: list[TranscriptSegment]


class ClipUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    title: Optional[str] = Field(default=None, max_length=120)
    reason: Optional[str] = None

    @model_validator(mode="after")
    def validate_clip_update(self) -> "ClipUpdate":
        if self.start_time is not None and self.end_time is not None and self.end_time <= self.start_time:
            raise ValueError("end_time must be greater than start_time")
        return self


class ClipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    start_time: float
    end_time: float
    title: str
    score: float
    reason: str
    s3_path: str
    status: str


class RenderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    clip_id: int
    status: str


class IngestURLRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    url: str


class StatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    video_id: int
    status: str
    progress_stage: Optional[str]
    duration: Optional[float]
    clips: list[ClipResponse]
    error_message: Optional[str]
