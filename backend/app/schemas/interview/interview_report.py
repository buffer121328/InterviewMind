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

    overall_assessment: str = Field(default="", description="整体评价摘要")
    recommendation: str = Field(default="", description="录用建议：hire/maybe/no_hire")
    dimensions: dict[str, dict[str, Any]] = Field(default_factory=dict, description="各能力维度评分（维度名 -> 评分详情）")
    skill_tags: list[str] = Field(default_factory=list, description="技能标签列表")
    key_strengths: list[str] = Field(default_factory=list, description="主要优势")
    key_weaknesses: list[str] = Field(default_factory=list, description="主要不足")
    generation_mode: str = Field(default="model_reviewed", description="生成模式：model_reviewed/degraded_evidence_only/not_ready")
    missing_dimensions: list[str] = Field(default_factory=list, description="降级时未生成评分的能力维度")


class StructuredWeaknessReport(BaseModel):
    """面向报告 UI 的短板、证据与行动集合。"""

    question_evidence: list[QuestionEvidence] = Field(default_factory=list, description="题目相关证据列表")
    weakness_categories: list[WeaknessCategory] = Field(default_factory=list, description="短板类别列表")
    question_failures: list[QuestionFailure] = Field(default_factory=list, description="未通过/失败题目列表")
    improvement_actions: list[ImprovementAction] = Field(default_factory=list, description="改进动作列表")
    recommended_questions: list[str] = Field(default_factory=list, description="推荐后续练习题目")
    priority_order: list[str] = Field(default_factory=list, description="短板优先级排序（短板类别名）")
    generation_mode: str = Field(default="model_reviewed", description="生成模式：model_reviewed/degraded_evidence_only/not_ready")
    degradation_reason: str = Field(default="", description="降级原因说明")
    missing_dimensions: list[str] = Field(default_factory=list, description="降级时未生成评分的维度")


class SaveReportQuestionsRequest(BaseModel):
    """保存报告推荐题时只接受持久化列表索引，不信任客户端题目正文。"""

    question_indices: list[int] = Field(min_length=1, max_length=20, description="待保存的推荐题索引列表（1-20 个）")


class SaveReportQuestionsResponse(BaseModel):
    """推荐题批量保存结果。"""

    success: bool = Field(default=True, description="是否保存成功")
    saved_count: int = Field(default=0, description="成功保存的题目数")
    skipped_count: int = Field(default=0, description="跳过的题目数")
    item_ids: list[int] = Field(default_factory=list, description="已保存的题目 ID 列表")


class ReportArtifactMetadata(BaseModel):
    """报告读取接口允许暴露的 PDF 产物元数据。"""

    id: int = Field(description="产物记录 ID")
    title: str = Field(description="报告标题")
    format: str = Field(default="pdf", description="产物格式")
    mime_type: str = Field(default="application/pdf", description="MIME 类型")
    size_bytes: int = Field(default=0, description="产物文件大小（字节）")
    created_at: str = Field(description="创建时间")
    download_url: str = Field(description="下载链接")
    artifact_mode: InterviewReportMode = Field(default=InterviewReportMode.DEEP, description="报告模式")
    report_source_version: str = Field(default="legacy", description="报告来源版本指纹")
