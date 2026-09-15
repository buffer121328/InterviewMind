"""面试相关的请求/响应数据模型（聊天、开始面试、回退、画像、报告）。"""

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from app.domain.interview_rounds import resolve_max_questions, resolve_round_type
from app.schemas.jobs.job_context import JobContextSnapshot
from app.schemas.schemas import ApiConfig


class ChatRequest(BaseModel):
    """提交一条面试回复的请求体；校验后补全轮次类型与最大题数默认值。"""
    message: str = Field(..., description="用户消息内容")
    thread_id: str = Field(..., description="会话线程ID")
    mode: Literal["mock"] = Field(default="mock", description="面试模式")
    resume_context: str = Field(..., description="简历上下文")
    job_description: str = Field(..., description="岗位描述")
    company_info: str = Field(default="未知", description="公司背景信息")
    max_questions: int | None = Field(default=None, ge=1, le=20, description="最大问题数量；不传时按面试类型默认")
    round_type: str = Field(default="tech_initial", description="面试类型：tech_initial/tech_deep/hr_comprehensive")

    # 模型校验后执行：统一收口轮次类型与最大题数的默认值/边界校验
    @model_validator(mode="after")
    def resolve_question_defaults(self):
        """校验后解析轮次类型与最大题数，并补全默认值、做边界校验。"""
        self.round_type = resolve_round_type(self.round_type)
        self.max_questions = resolve_max_questions(self.round_type, self.max_questions)
        return self
    # 用户配置（可选）
    user_id: Optional[str] = Field(default=None, description="用户标识")
    api_config: Optional[ApiConfig] = Field(default=None, description="用户自定义 API 配置")


class ChatStreamResponse(BaseModel):
    """SSE 聊天流中的一帧；type 取值：plan/step_update/token/state_update/error/done。"""
    type: str = Field(..., description="响应类型: plan, step_update, token, state_update, error, done")
    content: Optional[str] = Field(None, description="响应内容")


class InterviewStartRequest(BaseModel):
    """发起一场新面试的请求体；校验后补全轮次类型与最大题数默认值。"""
    thread_id: str = Field(..., description="会话线程ID")
    mode: Literal["mock"] = Field(..., description="面试模式")
    resume_context: Optional[str] = Field(default=None, description="简历上下文（下一轮面试时可从数据库加载）")
    resume_filename: str = Field(default="", description="简历文件名")
    job_description: Optional[str] = Field(default=None, description="岗位描述（下一轮面试时可从数据库加载）")
    company_info: str = Field(default="未知", description="公司背景信息")
    job_context_snapshot: Optional[JobContextSnapshot] = Field(default=None, description="来源岗位与实际编辑上下文快照")
    max_questions: int | None = Field(default=None, ge=1, le=20, description="最大问题数量；不传时按面试类型默认")
    round_type: str = Field(default="tech_initial", description="面试类型：tech_initial/tech_deep/hr_comprehensive")

    # 模型校验后执行：统一收口轮次类型与最大题数的默认值/边界校验
    @model_validator(mode="after")
    def resolve_question_defaults(self):
        """校验后解析轮次类型与最大题数，并补全默认值、做边界校验。"""
        self.round_type = resolve_round_type(self.round_type)
        self.max_questions = resolve_max_questions(self.round_type, self.max_questions)
        return self
    question_bank_count: int = Field(default=0, ge=0, le=10, description="从个人题库抽取的题数")
    # 用户配置（可选）
    user_id: Optional[str] = Field(default=None, description="用户标识")
    api_config: Optional[ApiConfig] = Field(default=None, description="用户自定义 API 配置")


class RollbackRequest(BaseModel):
    """回退到指定消息索引的请求体"""
    thread_id: str = Field(..., description="会话线程ID")
    index: int = Field(..., description="回退到的消息索引（0-based）")


class ProfileGenerateRequest(BaseModel):
    """画像生成请求"""
    user_id: Optional[str] = Field(default=None, description="用户标识")
    api_config: Optional[ApiConfig] = Field(default=None, description="用户自定义 API 配置")


class InterviewReportRunRequest(BaseModel):
    """触发面试报告生成的后台任务请求。"""
    session_id: str = Field(..., description="面试会话 ID，报告据此生成")
    api_config: Optional[ApiConfig] = Field(default=None, description="用户自定义 API 配置")
