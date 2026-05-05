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


class TranscriptSegmentSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    start: float
    end: float
    speaker: Optional[str] = None
    text: str


class TranscriptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    video_id: int
    language: str
    full_text: str
    segments: list[TranscriptSegmentSchema]


class ClipUpdateRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    title: Optional[str] = Field(default=None, max_length=120)
    layout_mode: Optional[str] = None

    @model_validator(mode="after")
    def validate_clip_update(self) -> "ClipUpdateRequest":
        if self.layout_mode is not None and self.layout_mode not in {"center", "speaker", "split"}:
            raise ValueError("layout_mode must be one of: center, speaker, split")

        if self.start_time is not None and self.end_time is not None:
            duration = self.end_time - self.start_time
            if duration < 10 or duration > 120:
                raise ValueError("clip duration must be between 10 and 120 seconds")

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
    layout_mode: Optional[str] = None


class RenderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    clip_id: int
    status: str


class IngestUrlRequest(BaseModel):
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
