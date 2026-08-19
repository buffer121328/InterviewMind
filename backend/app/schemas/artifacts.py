"""产物（简历/报告等）导出与查询的 HTTP 数据模型。"""

from typing import Literal

from pydantic import BaseModel, Field

ArtifactFormat = Literal["html", "pdf"]  # 支持的产物格式
ArtifactMode = Literal["default", "standard", "deep"]
ArtifactSourceType = Literal[  # 产物来源：生成的简历/Agent 运行/简历结果/JD 分析/短板报告/面试报告
    "generated_resume",
    "agent_run",
    "resume_result",
    "jd_analysis",
    "weakness_report",
    "interview_report",
]


class ArtifactExportRequest(BaseModel):
    """产物导出请求：按来源类型与来源 ID 选择要导出的产物，并指定输出格式。"""

    source_type: ArtifactSourceType = Field(..., description="产物来源类型")
    source_id: str = Field(min_length=1, max_length=128, description="来源记录 ID")
    format: ArtifactFormat = Field(..., description="导出格式：html/pdf")
    artifact_mode: ArtifactMode | None = Field(default=None, description="面试报告模式；非面试产物固定为 default")
    report_source_version: str | None = Field(default=None, max_length=128, description="报告权威来源版本")


class ArtifactResponse(BaseModel):
    """产物响应：单个产物的元数据与下载地址。"""

    id: int = Field(..., description="产物 ID")
    source_type: ArtifactSourceType = Field(..., description="产物来源类型")
    source_id: str = Field(..., description="来源记录 ID")
    title: str = Field(..., description="产物标题")
    format: ArtifactFormat = Field(..., description="产物格式：html/pdf")
    mime_type: str = Field(..., description="MIME 类型")
    size_bytes: int = Field(..., description="文件大小（字节）")
    created_at: str = Field(..., description="创建时间")
    download_url: str = Field(..., description="下载地址")
    artifact_mode: ArtifactMode = Field(default="default", description="产物模式")
    report_source_version: str = Field(default="legacy", description="报告权威来源版本")
