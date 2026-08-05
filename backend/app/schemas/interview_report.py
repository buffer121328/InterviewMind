"""结构化单场面试报告与训练交接请求模型。"""

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.llm_outputs import ImprovementAction, QuestionEvidence, QuestionFailure, WeaknessCategory


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

    success: bool = True
    saved_count: int = 0
    skipped_count: int = 0
    item_ids: list[int] = Field(default_factory=list)
