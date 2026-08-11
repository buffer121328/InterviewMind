"""提供产物相关后端功能。"""

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
    """定义产物请求相关后端数据结构或服务组件。"""

    source_type: ArtifactSourceType
    source_id: str = Field(min_length=1, max_length=128)
    format: ArtifactFormat


class ArtifactResponse(BaseModel):
    """定义产物响应相关后端数据结构或服务组件。"""

    id: int
    source_type: ArtifactSourceType
    source_id: str
    title: str
    format: ArtifactFormat
    mime_type: str
    size_bytes: int
    created_at: str
    download_url: str
