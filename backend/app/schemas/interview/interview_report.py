"""结构化单场面试报告与训练交接请求模型。"""

from typing import Any

from pydantic import BaseModel, Field

from app.domain.interview_report_modes import InterviewReportMode
from app.schemas.llm_outputs import (
    ImprovementAction,
    QuestionEvidence,
    QuestionFailure,
    WeaknessCategory,
)


class StructuredInterviewProfile(BaseModel):
    """面向报告 UI 的有界候选人画像。"""

    overall_assessment: str = ""
    recommendation: str = ""
    dimensions: dict[str, dict[str, Any]] = Field(default_factory=dict)
    skill_tags: list[str] = Field(default_factory=list)
    key_strengths: list[str] = Field(default_factory=list)
    key_weaknesses: list[str] = Field(default_factory=list)
    generation_mode: str = "model_reviewed"
    missing_dimensions: list[str] = Field(default_factory=list)


class StructuredWeaknessReport(BaseModel):
    """面向报告 UI 的短板、证据与行动集合。"""

    question_evidence: list[QuestionEvidence] = Field(default_factory=list)
    weakness_categories: list[WeaknessCategory] = Field(default_factory=list)
    question_failures: list[QuestionFailure] = Field(default_factory=list)
    improvement_actions: list[ImprovementAction] = Field(default_factory=list)
    recommended_questions: list[str] = Field(default_factory=list)
    priority_order: list[str] = Field(default_factory=list)
    generation_mode: str = "model_reviewed"
    degradation_reason: str = ""
    missing_dimensions: list[str] = Field(default_factory=list)


class SaveReportQuestionsRequest(BaseModel):
    """保存报告推荐题时只接受持久化列表索引，不信任客户端题目正文。"""

    question_indices: list[int] = Field(min_length=1, max_length=20)


class SaveReportQuestionsResponse(BaseModel):
    """推荐题批量保存结果。"""

    success: bool = Field(default=True, description="是否保存成功")
    saved_count: int = Field(default=0, description="成功保存的题目数")
    skipped_count: int = Field(default=0, description="跳过的题目数")
    item_ids: list[int] = Field(default_factory=list, description="已保存的题目 ID 列表")


class ReportArtifactMetadata(BaseModel):
    """报告读取接口允许暴露的 PDF 产物元数据。"""

    id: int
    title: str
    format: str = "pdf"
    mime_type: str = "application/pdf"
    size_bytes: int = 0
    created_at: str
    download_url: str
    artifact_mode: InterviewReportMode = InterviewReportMode.DEEP
    report_source_version: str = "legacy"
