"""
会话数据模型
定义面试会话的数据结构
"""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from app.clock import utc_now
from app.domain.interview_rounds import resolve_max_questions, resolve_round_type
from app.schemas.interview.interview_report import (
    StructuredInterviewProfile,
    StructuredWeaknessReport,
)
from app.schemas.jobs.job_context import JobContextSnapshot
from app.schemas.schemas import ApiConfig


class MessageItem(BaseModel):
    """单条消息模型"""
    role: Literal["user", "assistant", "system"] = Field(..., description="消息角色")
    content: str = Field(..., description="消息内容")
    timestamp: str = Field(default_factory=lambda: utc_now().isoformat(), description="消息时间戳")
    question_index: int = Field(default=0, description="对应的问题序号")
    audio_url: Optional[str] = Field(None, description="音频URL或ID")


class SessionMetadata(BaseModel):
    """会话元数据"""
    mode: Literal["mock", "voice"] = Field(..., description="面试模式")
    resume_filename: Optional[str] = Field(None, description="简历文件名")
    resume_content: Optional[str] = Field(None, description="简历全文内容")
    job_description: Optional[str] = Field(None, description="岗位描述")
    company_info: Optional[str] = Field(None, description="公司信息")
    source_job_id: Optional[int] = Field(None, description="来源岗位 ID")
    job_context_snapshot: Optional[JobContextSnapshot] = Field(None, description="创建面试时的岗位上下文快照")
    question_count: int = Field(default=0, description="当前主线题目进度（已完成题数/下一题索引）")
    max_questions: int = Field(default=10, ge=1, le=20, description="最大问题数量")
    status: Literal["active", "completed", "archived"] = Field(default="active", description="会话状态")
    pinned: bool = Field(default=False, description="是否置顶")
    # 多轮面试字段
    series_id: Optional[str] = Field(None, description="系列ID，串联所有轮次")
    round_index: int = Field(default=1, description="轮次序号：1, 2, 3...")
    round_type: str = Field(default="tech_initial", description="面试类型")
    parent_session_id: Optional[str] = Field(None, description="上一轮Session ID")
    interview_plan: List[Dict[str, Any]] = Field(default_factory=list, description="面试计划")
    company_profile: Optional[Dict[str, Any]] = Field(None, description="第三轮生成的公司总画像")
    report_source_version: Optional[str] = Field(None, description="报告权威来源版本")
    stable_context_version: Optional[str] = Field(None, description="稳定上下文版本")
    stable_context_fingerprint: Optional[str] = Field(None, description="稳定上下文指纹")
    round_strategy_version: Optional[str] = Field(None, description="轮次策略版本")
    turn_state_version: Optional[str] = Field(None, description="结构化面试状态版本")
    turn_state: Optional[Dict[str, Any]] = Field(None, description="结构化面试状态")
    turn_checkpoint_refs: List[Dict[str, Any]] = Field(default_factory=list, description="面试状态检查点引用")


class InterviewSession(BaseModel):
    """面试会话完整模型"""
    session_id: str = Field(..., description="会话ID (thread_id)")
    title: str = Field(..., description="会话标题")
    created_at: str = Field(default_factory=lambda: utc_now().isoformat(), description="创建时间")
    updated_at: str = Field(default_factory=lambda: utc_now().isoformat(), description="更新时间")
    metadata: SessionMetadata = Field(..., description="会话元数据")
    messages: List[MessageItem] = Field(default_factory=list, description="消息列表")


class SessionListItem(BaseModel):
    """会话列表项（简化版）"""
    session_id: str = Field(..., description="会话 ID")
    title: str = Field(..., description="会话标题")
    created_at: str = Field(..., description="创建时间")
    updated_at: str = Field(..., description="更新时间")
    mode: Literal["mock", "voice"] = Field(..., description="面试模式")
    status: Literal["active", "completed", "archived"] = Field(..., description="会话状态")
    message_count: int = Field(default=0, description="消息数量")
    question_count: int = Field(default=0, description="当前主线题目进度（已完成题数/下一题索引）")
    pinned: bool = Field(default=False, description="是否置顶")
    # 多轮面试字段
    round_index: int = Field(default=1, description="轮次序号")
    round_type: str = Field(default="tech_initial", description="面试类型")
    series_id: Optional[str] = Field(None, description="面试系列 ID")
    parent_session_id: Optional[str] = Field(None, description="上一轮会话 ID")
    company_info: Optional[str] = Field(None, description="公司信息")
    max_questions: int = Field(default=10, description="本轮最大主问题数")
    has_company_profile: bool = Field(default=False, description="是否已生成公司总画像")


class SessionCreateRequest(BaseModel):
    """创建会话请求"""
    title: Optional[str] = Field(None, description="会话标题（可选，自动生成）")
    mode: Literal["mock", "voice"] = Field(..., description="面试模式")
    resume_filename: Optional[str] = Field(None, description="简历文件名")
    job_description: Optional[str] = Field(None, description="岗位描述")
    max_questions: int | None = Field(default=None, ge=1, le=20, description="最大问题数量；不传时按面试类型默认")
    round_type: str = Field(default="tech_initial", description="面试类型")

    @model_validator(mode="after")
    def resolve_question_defaults(self):
        """校验后解析轮次类型与最大题数并补全默认值。"""
        self.round_type = resolve_round_type(self.round_type)
        self.max_questions = resolve_max_questions(self.round_type, self.max_questions)
        return self
    user_id: Optional[str] = Field(None, description="用户标识")


class RegenerateQuestionRequest(BaseModel):
    """当前题目重新生成请求。"""

    question_index: int = Field(..., ge=0, description="当前题目索引（从 0 开始）")
    reason: Optional[str] = Field(default=None, max_length=500, description="用户可选的重新生成原因")
    api_config: Optional[ApiConfig] = Field(default=None, description="请求级模型配置")


class RegenerateQuestionResponse(BaseModel):
    """当前题目重新生成响应。"""

    success: bool = Field(..., description="是否成功")
    question_index: int = Field(..., description="题目索引")
    question: Dict[str, Any] = Field(..., description="替换后的题目")


class SessionUpdateRequest(BaseModel):
    """更新会话请求"""
    title: Optional[str] = Field(None, description="会话标题")
    status: Optional[Literal["active", "completed", "archived"]] = Field(None, description="会话状态")
    metadata: Optional[Dict[str, Any]] = Field(None, description="元数据更新")


class SessionListResponse(BaseModel):
    """会话列表响应"""
    success: bool = Field(..., description="是否成功")
    sessions: List[SessionListItem] = Field(..., description="会话列表")
    total: int = Field(..., description="总数量")


class SessionDetailResponse(BaseModel):
    """会话详情响应"""
    success: bool = Field(..., description="是否成功")
    session: InterviewSession = Field(..., description="会话详情")


class SessionMarkdownReportResponse(BaseModel):
    """返回唯一深度报告。"""

    success: bool = Field(description="能力画像和短板数据是否均已生成")
    session_id: str = Field(description="当前 owner 可见的面试会话 ID")
    status: Literal["not_ready", "ready", "degraded"] = Field(default="not_ready", description="报告状态")
    markdown: str = Field(default="", description="用于预览和导出的统一 Markdown")
    generated_at: Optional[str] = Field(default=None, description="报告数据最近更新时间")
    message: Optional[str] = Field(default=None, description="报告尚不可用时的稳定提示")
    company_profile: Optional[Dict[str, Any]] = Field(default=None, description="第三轮对应的公司总画像")
    profile: Optional[StructuredInterviewProfile] = Field(default=None, description="结构化能力画像")
    weakness_report: Optional[StructuredWeaknessReport] = Field(default=None, description="结构化短板、证据与行动")
