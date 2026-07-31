"""Bounded request and response contracts for private report exports."""

from typing import Literal

from pydantic import BaseModel, Field


ArtifactFormat = Literal["html", "pdf"]
ArtifactSourceType = Literal[
    "generated_resume",
    "agent_run",
    "resume_result",
    "jd_analysis",
    "weakness_report",
    "interview_report",
]


class ArtifactExportRequest(BaseModel):
    """Request one export from an existing owner-scoped report source."""

    source_type: ArtifactSourceType
    source_id: str = Field(min_length=1, max_length=128)
    format: ArtifactFormat


class ArtifactResponse(BaseModel):
    """Safe artifact metadata; storage keys are intentionally never returned."""

    id: int
    source_type: ArtifactSourceType
    source_id: str
    title: str
    format: ArtifactFormat
    mime_type: str
    size_bytes: int
    created_at: str
    download_url: str
