"""
Pydantic 数据模型定义
用于 FastAPI 的请求和响应数据验证
"""

from typing import List, Literal, Optional
from pydantic import BaseModel, Field
from enum import Enum


# ============================================================================
# 用户 API 配置模型
# ============================================================================

class ModelChannelConfig(BaseModel):
    """单个通道的模型配置"""
    api_key: str = Field(..., description="API Key")
    base_url: str = Field(..., description="API Base URL")
    model: str = Field(..., description="模型名称")


class ModelPoolMemberConfig(ModelChannelConfig):
    """模型池成员；weight 用于请求级加权轮询。"""

    name: Optional[str] = Field(default=None, description="便于观测的模型配置名称")
    weight: int = Field(default=1, ge=1, le=100, description="调度权重")


class ApiConfig(BaseModel):
    """用户自定义的 API 配置 - 支持多通道独立配置"""
    smart: ModelChannelConfig = Field(..., description="Smart 通道配置（复杂任务）")
    fast: ModelChannelConfig = Field(..., description="Fast 通道配置（快速响应）")
    reasoning_pool: List[ModelPoolMemberConfig] = Field(
        default_factory=list,
        description="推理模型池；为空时兼容回退到 smart 单模型",
    )
    fast_pool: List[ModelPoolMemberConfig] = Field(
        default_factory=list,
        description="快速模型池；为空时兼容回退到 fast 单模型",
    )
    # 简历工具专家通道（可选，未配置时回退到 smart）
    general: Optional[ModelChannelConfig] = Field(default=None, description="通用任务通道（简历分析、主持人）")
    match_analyst: Optional[ModelChannelConfig] = Field(default=None, description="匹配分析师通道")
    content_writer: Optional[ModelChannelConfig] = Field(default=None, description="内容优化师通道")
    hr_reviewer: Optional[ModelChannelConfig] = Field(default=None, description="HR审核官通道")
    reflector: Optional[ModelChannelConfig] = Field(default=None, description="质量审核通道")
    voice: Optional[ModelChannelConfig] = Field(default=None, description="语音面试通道，未配置时回退到 fast")



# ============================================================================
# 请求/响应模型
# ============================================================================

class ChatRequest(BaseModel):
    """聊天请求模型"""
    message: str = Field(..., description="用户消息内容")
    thread_id: str = Field(..., description="会话线程ID")
    mode: Literal["mock"] = Field(default="mock", description="面试模式")
    resume_context: str = Field(..., description="简历上下文")
    job_description: str = Field(..., description="岗位描述")
    company_info: str = Field(default="未知", description="公司背景信息")
    max_questions: int = Field(default=5, ge=1, le=20, description="最大问题数量")
    # 用户配置（可选）
    user_id: Optional[str] = Field(default=None, description="用户标识")
    api_config: Optional[ApiConfig] = Field(default=None, description="用户自定义 API 配置")


class ChatStreamResponse(BaseModel):
    """聊天流式响应模型"""
    type: str = Field(..., description="响应类型: plan, step_update, token, state_update, error, done")
    content: Optional[str] = Field(None, description="响应内容")
    

class FileUploadResponse(BaseModel):
    """文件上传响应模型"""
    success: bool = Field(..., description="上传是否成功")
    message: str = Field(..., description="响应消息")
    filename: Optional[str] = Field(None, description="存储的文件名")
    content_length: Optional[int] = Field(None, description="提取的文本长度")
    text_content: Optional[str] = Field(None, description="提取的文本内容")


class ResumeInfo(BaseModel):
    """简历信息模型"""
    original_name: str = Field(..., description="原始文件名")
    stored_name: str = Field(..., description="存储的文件名")
    upload_time: str = Field(..., description="上传时间")
    file_size: int = Field(..., description="文件大小（字节）")
    content_length: int = Field(..., description="文本内容长度")
    use_count: int = Field(default=0, description="使用次数")
    last_used: Optional[str] = Field(None, description="最后使用时间")


class InterviewCandidateQuestion(BaseModel):
    """仅用于本次面试计划的受限候选题。"""

    question_text: str = Field(min_length=2, max_length=500)
    reference_answer: Optional[str] = Field(default=None, max_length=10_000)
    tags: List[str] = Field(default_factory=list, max_length=10)
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    target_skill: Optional[str] = Field(default=None, max_length=100)
    question_type: Literal["intro", "tech", "behavior", "system_design"] = "tech"
    source_type: str = Field(default="experience", max_length=100)
    source_id: str = Field(max_length=200)


class InterviewStartRequest(BaseModel):
    """面试开始请求模型"""
    thread_id: str = Field(..., description="会话线程ID")
    mode: Literal["mock"] = Field(..., description="面试模式")
    resume_context: Optional[str] = Field(default=None, description="简历上下文（下一轮面试时可从数据库加载）")
    resume_filename: str = Field(default="", description="简历文件名")
    job_description: Optional[str] = Field(default=None, description="岗位描述（下一轮面试时可从数据库加载）")
    company_info: str = Field(default="未知", description="公司背景信息")
    max_questions: int = Field(default=5, ge=1, le=20, description="最大问题数量")
    question_bank_count: int = Field(default=0, ge=0, le=20, description="从个人题库抽取的题数")
    experience_questions: List[InterviewCandidateQuestion] = Field(
        default_factory=list,
        max_length=20,
        description="本次面试直接使用、但不强制入库的面经候选题",
    )
    # 用户配置（可选）
    user_id: Optional[str] = Field(default=None, description="用户标识")
    api_config: Optional[ApiConfig] = Field(default=None, description="用户自定义 API 配置")


class ErrorResponse(BaseModel):
    """错误响应模型"""
    error: str = Field(..., description="错误类型")
    message: str = Field(..., description="错误消息")
    details: Optional[dict] = Field(None, description="错误详情")


class RollbackRequest(BaseModel):
    """回退请求模型"""
    thread_id: str = Field(..., description="会话线程ID")
    index: int = Field(..., description="回退到的消息索引（0-based）")


class ApiConfigValidateRequest(BaseModel):
    """API 配置验证请求"""
    api_key: str = Field(..., description="API Key")
    base_url: str = Field(..., description="API Base URL")
    model: str = Field(..., description="模型名称")


class ProfileGenerateRequest(BaseModel):
    """画像生成请求"""
    user_id: Optional[str] = Field(default=None, description="用户标识")
    api_config: Optional[ApiConfig] = Field(default=None, description="用户自定义 API 配置")


class WeaknessGenerateRequest(BaseModel):
    """短板地图生成请求"""
    session_id: str = Field(..., description="会话 ID")
    api_config: Optional[ApiConfig] = Field(default=None, description="用户自定义 API 配置")
