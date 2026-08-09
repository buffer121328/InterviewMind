"""面经采集与题库导入契约。"""

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator

from app.schemas.schemas import ApiConfig

ExperienceSource = Literal["nowcoder"]


class ExportedExperienceItem(BaseModel):
    """数据对象，承载 `ExportedExperienceItem` 的结构化字段和跨模块契约；只表达数据，不在构造或序列化时执行外部调用。"""
    id: str | None = Field(default=None, max_length=200)
    title: str = Field(default="", max_length=500)
    content: str | None = Field(default=None, max_length=50_000)
    desc: str | None = Field(default=None, max_length=50_000)
    url: HttpUrl | None = None
    query: str | None = Field(default=None, max_length=100)
    keyword: str | None = Field(default=None, max_length=100)


class ExperienceCollectRequest(BaseModel):
    """API 请求数据对象，定义 `ExperienceCollect` 的字段校验和反序列化契约；只承载数据，不执行业务副作用。"""
    source: ExperienceSource
    queries: list[str] = Field(default_factory=list, max_length=5)
    max_pages: int = Field(default=1, ge=1, le=3)
    exported_items: list[ExportedExperienceItem] = Field(default_factory=list, max_length=100)
    api_config: ApiConfig | None = Field(default=None, description="用于面经题质量治理的请求级模型配置")


class ExperienceSummary(BaseModel):
    """数据对象，承载 `ExperienceSummary` 的结构化字段和跨模块契约；只表达数据，不在构造或序列化时执行外部调用。"""
    source: str
    source_id: str
    title: str
    url: str = ""
    query: str = ""
    content_preview: str


class ExperienceQuestionCandidate(BaseModel):
    """围绕 `ExperienceQuestionCandidate` 的领域对象，集中表达其职责、边界和与相邻模块的协作契约。"""
    question_text: str = Field(min_length=5, max_length=500)
    reference_answer: str | None = None
    tags: list[str] = Field(default_factory=list, max_length=10)
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    target_skill: str | None = Field(default=None, max_length=100)
    question_type: Literal["intro", "tech", "behavior", "system_design"] = "tech"
    source_type: str = Field(max_length=100)
    source_id: str = Field(max_length=200)


class ExperienceGovernedQuestion(BaseModel):
    """模型对一个有界候选题给出的质量决定与结构化复习数据。"""

    candidate_index: int = Field(ge=0)
    keep: bool
    question_text: str = Field(min_length=5, max_length=500)
    answer_points: list[str] = Field(default_factory=list, max_length=5)
    tags: list[str] = Field(default_factory=list, max_length=10)
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    target_skill: str | None = Field(default=None, max_length=100)
    question_type: Literal["intro", "tech", "behavior", "system_design"] = "tech"
    rejection_reason: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_kept_answer_points(self):
        """Require concise answer points for every question allowed into the bank."""
        points = [point.strip() for point in self.answer_points if point.strip()]
        if self.keep and not 2 <= len(points) <= 5:
            raise ValueError("保留题目必须包含 2 至 5 条回答要点")
        self.answer_points = points
        return self


class ExperienceGovernanceOutput(BaseModel):
    """面经候选题批量治理的结构化模型输出。"""

    questions: list[ExperienceGovernedQuestion] = Field(max_length=100)


class ExperienceCollectResponse(BaseModel):
    """面经采集、模型治理和直接入库的 owner 可见摘要。"""
    success: bool = True
    experiences: list[ExperienceSummary] = Field(default_factory=list)
    questions: list[ExperienceQuestionCandidate] = Field(default_factory=list)
    document_count: int = 0
    candidate_count: int = 0
    filtered_count: int = 0
    duplicate_count: int = 0
    imported_count: int = 0
    failed_count: int = 0
    import_id: int | None = None
    message: str | None = None


class ExperienceQuestionImportRequest(BaseModel):
    """API 请求数据对象，定义 `ExperienceQuestionImport` 的字段校验和反序列化契约；只承载数据，不执行业务副作用。"""
    questions: list[ExperienceQuestionCandidate] = Field(min_length=1, max_length=200)


class ExperienceQuestionImportResponse(BaseModel):
    """API 响应数据对象，定义 `ExperienceQuestionImport` 的序列化契约；只暴露当前 owner 可见且已脱敏的结果。"""
    success: bool
    total_count: int
    success_count: int
    import_id: int | None = None
    message: str | None = None
