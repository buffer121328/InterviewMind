"""面经采集与题库导入契约。"""

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


ExperienceSource = Literal["nowcoder", "xiaohongshu"]


class ExportedExperienceItem(BaseModel):
    """数据对象，承载 `ExportedExperienceItem` 的结构化字段和跨模块契约；只表达数据，不在构造或序列化时执行外部调用。"""
    id: str | None = Field(default=None, max_length=200)
    note_id: str | None = Field(default=None, max_length=200)
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


class ExperienceCollectResponse(BaseModel):
    """API 响应数据对象，定义 `ExperienceCollect` 的序列化契约；只暴露当前 owner 可见且已脱敏的结果。"""
    success: bool = True
    experiences: list[ExperienceSummary] = Field(default_factory=list)
    questions: list[ExperienceQuestionCandidate] = Field(default_factory=list)
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
