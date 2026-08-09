"""
题库相关数据模型
用于面试题的上传、沉淀、检索
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

QuestionPriority = Literal["required", "high", "low"]
QuestionType = Literal["intro", "tech", "behavior", "system_design"]
QuestionDifficulty = Literal["easy", "medium", "hard"]


class QuestionBankFollowup(BaseModel):
    """题库主问题沉淀的追问。"""
    id: Optional[int] = Field(default=None, description="追问 ID")
    parent_question_id: int = Field(description="主问题 ID")
    question_text: str = Field(description="追问内容")
    reference_answer: Optional[str] = Field(default=None, description="追问参考答案")
    trigger_condition: Optional[str] = Field(default=None, description="触发该追问的条件")
    source_session_id: Optional[str] = Field(default=None, description="来源面试会话 ID")
    created_at: Optional[str] = Field(default=None, description="创建时间")
    updated_at: Optional[str] = Field(default=None, description="更新时间")


class QuestionBankItem(BaseModel):
    """题库条目"""
    id: Optional[int] = Field(default=None, description="条目 ID")
    user_id: str = Field(description="用户 ID")
    source_type: str = Field(
        default="manual",
        description="来源类型: manual(手动上传)/generated(面试生成)/imported(批量导入)"
    )
    source_id: Optional[str] = Field(default=None, description="来源 ID（如 session_id）")
    origin_session_id: Optional[str] = Field(default=None, description="来源面试会话 ID")
    question_text: str = Field(min_length=2, max_length=500, description="题目内容")
    reference_answer: Optional[str] = Field(default=None, description="参考答案")
    tags: List[str] = Field(default_factory=list, description="标签列表")
    difficulty: QuestionDifficulty = Field(
        default="medium",
        description="难度: easy/medium/hard"
    )
    target_skill: Optional[str] = Field(default=None, description="考察技能")
    question_type: QuestionType = Field(
        default="tech",
        description="题目类型: intro/tech/behavior/system_design"
    )
    priority: QuestionPriority = Field(default="low", description="优先级: required/high/low")
    is_verified: bool = Field(default=False, description="是否已验证")
    usage_count: int = Field(default=0, description="使用次数")
    created_at: Optional[str] = Field(default=None, description="创建时间")
    updated_at: Optional[str] = Field(default=None, description="更新时间")
    followups: List[QuestionBankFollowup] = Field(default_factory=list, description="关联追问列表")


class QuestionBankImport(BaseModel):
    """题库导入记录"""
    id: Optional[int] = Field(default=None, description="导入记录 ID")
    user_id: str = Field(description="用户 ID")
    import_source: str = Field(default="file", description="导入来源: file/api/manual")
    import_status: str = Field(
        default="pending",
        description="导入状态: pending/processing/completed/failed"
    )
    file_name: Optional[str] = Field(default=None, description="文件名")
    total_count: int = Field(default=0, description="总题目数")
    success_count: int = Field(default=0, description="成功导入数")
    summary: Optional[str] = Field(default=None, description="导入摘要")
    created_at: Optional[str] = Field(default=None, description="创建时间")


class QuestionBankCreateRequest(BaseModel):
    """创建题库条目请求"""
    question_text: str = Field(min_length=2, max_length=500, description="题目内容")
    reference_answer: Optional[str] = Field(default=None, max_length=10_000, description="回答要点")
    tags: List[str] = Field(default_factory=list, max_length=10, description="标签列表")
    difficulty: QuestionDifficulty = Field(default="medium", description="难度")
    target_skill: Optional[str] = Field(default=None, max_length=100, description="考察技能")
    question_type: QuestionType = Field(default="tech", description="题目类型")
    priority: QuestionPriority = Field(default="low", description="优先级")
    source_type: str = Field(default="manual", max_length=100, description="来源类型")


class QuestionBankListResponse(BaseModel):
    """题库列表响应"""
    success: bool = Field(description="是否成功")
    items: List[QuestionBankItem] = Field(default_factory=list, description="题库条目列表")
    total: int = Field(default=0, description="总数")
    message: Optional[str] = Field(default=None, description="消息")


class QuestionBankImportItem(BaseModel):
    """批量导入中的单道受约束题目，兼容 question_text/content 两种题干字段。"""

    question_text: Optional[str] = Field(default=None, max_length=500)
    content: Optional[str] = Field(default=None, max_length=500)
    reference_answer: Optional[str] = Field(default=None, max_length=10_000)
    tags: List[str] = Field(default_factory=list, max_length=10)
    difficulty: QuestionDifficulty = "medium"
    target_skill: Optional[str] = Field(default=None, max_length=100)
    question_type: QuestionType = "tech"
    priority: QuestionPriority = "low"
    source_type: Optional[str] = Field(default=None, max_length=100)
    source_id: Optional[str] = Field(default=None, max_length=200)

    @property
    def resolved_question_text(self) -> str:
        """Return the compatible non-empty question text."""
        return str(self.question_text or self.content or "").strip()


class QuestionBankImportRequest(BaseModel):
    """题库导入请求"""
    questions: List[QuestionBankImportItem] = Field(min_length=1, max_length=500, description="题目列表")
    import_source: str = Field(default="manual", description="导入来源")


class QuestionBankImportResponse(BaseModel):
    """题库导入响应"""
    success: bool = Field(description="是否成功")
    import_id: Optional[int] = Field(default=None, description="导入记录 ID")
    total_count: int = Field(default=0, description="总数")
    success_count: int = Field(default=0, description="成功数")
    message: Optional[str] = Field(default=None, description="消息")


class QuestionFileCandidate(BaseModel):
    """上传文件解析得到、尚未入库的候选题。"""
    question_text: str = Field(min_length=5, max_length=500)
    reference_answer: Optional[str] = Field(default=None, max_length=10_000)
    tags: List[str] = Field(default_factory=list, max_length=10)
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    target_skill: Optional[str] = Field(default=None, max_length=100)
    question_type: Literal["intro", "tech", "behavior", "system_design"] = "tech"
    priority: QuestionPriority = "low"
    source_type: str = Field(default="upload", max_length=100)
    source_id: str = Field(max_length=200)


class QuestionFilePreviewResponse(BaseModel):
    """API 响应数据对象，定义 `QuestionFilePreview` 的序列化契约；只暴露当前 owner 可见且已脱敏的结果。"""
    success: bool
    filename: str
    questions: List[QuestionFileCandidate] = Field(default_factory=list)
    message: Optional[str] = None
