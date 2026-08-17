"""面经采集与题库导入契约。"""

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator

from app.schemas.schemas import ApiConfig

ExperienceSource = Literal["nowcoder"]  # 面经来源：牛客


class ExportedExperienceItem(BaseModel):
    """浏览器导出的一条面经原始记录（含 URL/关键词）。"""
    id: str | None = Field(default=None, max_length=200, description="来源内唯一 ID")
    title: str = Field(default="", max_length=500, description="标题")
    content: str | None = Field(default=None, max_length=50_000, description="正文")
    desc: str | None = Field(default=None, max_length=50_000, description="描述")
    url: HttpUrl | None = Field(default=None, description="原文链接")
    query: str | None = Field(default=None, max_length=100, description="搜索词")
    keyword: str | None = Field(default=None, max_length=100, description="关键词")


class ExperienceCollectRequest(BaseModel):
    """发起面经采集的请求。"""
    source: ExperienceSource = Field(description="面经来源")
    queries: list[str] = Field(default_factory=list, max_length=5, description="触发采集的搜索词列表")
    max_pages: int = Field(default=1, ge=1, le=3, description="最大抓取页数")
    exported_items: list[ExportedExperienceItem] = Field(default_factory=list, max_length=100, description="浏览器导出的原始记录列表")
    api_config: ApiConfig | None = Field(default=None, description="用于面经题质量治理的请求级模型配置")


class ExperienceSummary(BaseModel):
    """面经采集结果的摘要。"""
    source: str = Field(description="来源标识")
    source_id: str = Field(description="来源内唯一 ID")
    title: str = Field(description="标题")
    url: str = Field(default="", description="原文链接，可空")
    query: str = Field(default="", description="触发采集的搜索词，可空")
    content_preview: str = Field(description="正文摘要")


class ExperienceQuestionCandidate(BaseModel):
    """从面经提炼、待质量治理的候选题。"""
    question_text: str = Field(min_length=5, max_length=500, description="题目文本")
    reference_answer: str | None = Field(default=None, description="参考答案")
    tags: list[str] = Field(default_factory=list, max_length=10, description="标签")
    difficulty: Literal["easy", "medium", "hard"] = Field(default="medium", description="难度")
    target_skill: str | None = Field(default=None, max_length=100, description="目标技能")
    question_type: Literal["intro", "tech", "behavior", "system_design"] = Field(default="tech", description="题目类型")
    source_type: str = Field(max_length=100, description="来源类型")
    source_id: str = Field(max_length=200, description="来源内唯一 ID")


class ExperienceGovernedQuestion(BaseModel):
    """模型对一个有界候选题给出的质量决定与结构化复习数据。"""

    candidate_index: int = Field(ge=0, description="候选题索引")
    keep: bool = Field(description="是否保留入库")
    question_text: str = Field(min_length=5, max_length=500, description="题目文本")
    answer_points: list[str] = Field(default_factory=list, max_length=5, description="回答要点")
    tags: list[str] = Field(default_factory=list, max_length=10, description="标签")
    difficulty: Literal["easy", "medium", "hard"] = Field(default="medium", description="难度")
    target_skill: str | None = Field(default=None, max_length=100, description="目标技能")
    question_type: Literal["intro", "tech", "behavior", "system_design"] = Field(default="tech", description="题目类型")
    rejection_reason: str | None = Field(default=None, max_length=200, description="拒绝原因")

    @model_validator(mode="after")
    def validate_kept_answer_points(self):
        """保留入库的题目必须包含 2-5 条回答要点，否则拒绝。"""
        points = [point.strip() for point in self.answer_points if point.strip()]
        if self.keep and not 2 <= len(points) <= 5:
            raise ValueError("保留题目必须包含 2 至 5 条回答要点")
        self.answer_points = points
        return self


class ExperienceGovernanceOutput(BaseModel):
    """面经候选题批量治理的结构化模型输出。"""

    questions: list[ExperienceGovernedQuestion] = Field(max_length=100, description="治理后的候选题列表")


class ExperienceCollectResponse(BaseModel):
    """面经采集、模型治理和直接入库的 owner 可见摘要。"""
    success: bool = Field(default=True, description="是否成功")
    experiences: list[ExperienceSummary] = Field(default_factory=list, description="采集到的面经摘要列表")
    questions: list[ExperienceQuestionCandidate] = Field(default_factory=list, description="提炼出的候选题列表")
    document_count: int = Field(default=0, description="采集到的文档数")
    candidate_count: int = Field(default=0, description="候选题数")
    filtered_count: int = Field(default=0, description="被过滤数")
    duplicate_count: int = Field(default=0, description="去重数")
    imported_count: int = Field(default=0, description="已导入数")
    failed_count: int = Field(default=0, description="失败数")
    import_id: int | None = Field(default=None, description="导入任务 ID")
    message: str | None = Field(default=None, description="提示信息")


class ExperienceQuestionImportRequest(BaseModel):
    """批量导入候选题到题库的请求。"""
    questions: list[ExperienceQuestionCandidate] = Field(min_length=1, max_length=200, description="候选题列表")


class ExperienceQuestionImportResponse(BaseModel):
    """候选题导入结果。"""
    success: bool = Field(description="是否成功")
    total_count: int = Field(description="提交总数")
    success_count: int = Field(description="成功数")
    import_id: int | None = Field(default=None, description="导入任务 ID")
    message: str | None = Field(default=None, description="提示信息")
