"""
Pydantic 数据模型定义
用于 FastAPI 的请求和响应数据验证
"""

from typing import List, Literal, Optional
from pydantic import BaseModel, Field


# ============================================================================
# 用户 API 配置模型
# ============================================================================

class ModelChannelConfig(BaseModel):
    """单个通道的模型配置；provider 字段只用于路由和观测，不包含凭据。"""
    credential_id: Optional[str] = Field(default=None, description="Redis 中的技术模型名凭据引用")
    api_key: str = Field(default="", description="由后端凭据中间件注入，前端业务请求不得直接填写")
    base_url: str = Field(..., description="API Base URL")
    model: str = Field(..., description="模型名称")
    provider: Optional[str] = Field(default=None, description="服务商标识，如 deepseek/qwen/openai_compatible")
    integration: Optional[str] = Field(default=None, description="LangChain 集成方式，如 deepseek/qwen/openai_compatible")
    pricing_key: Optional[str] = Field(default=None, description="本地价格表键名；缺省使用 model")
    dimensions: Optional[int] = Field(
        default=None,
        ge=1,
        le=16_000,
        strict=True,
        description="Embedding 输出维度；未提供时使用服务端兼容回退",
    )


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
    # 简历工具专家通道（可选，专属通道未配置时先回退到 general）
    general: Optional[ModelChannelConfig] = Field(default=None, description="简历专家通用/主持人通道；不参与 Smart/Fast 核心回退")
    match_analyst: Optional[ModelChannelConfig] = Field(default=None, description="匹配分析师专属通道；未配置时回退到 general")
    content_writer: Optional[ModelChannelConfig] = Field(default=None, description="内容优化师专属通道；未配置时回退到 general")
    hr_reviewer: Optional[ModelChannelConfig] = Field(default=None, description="HR 审核官专属通道；未配置时回退到 general")
    reflector: Optional[ModelChannelConfig] = Field(default=None, description="质量审核专属通道；未配置时回退到 general")
    mimo: Optional[ModelChannelConfig] = Field(default=None, description="MiMo ASR/文本/TTS 拆分语音通道")
    # 检索/记忆通道（可选，未配置时回退到服务端 .env）
    rag_embedding: Optional[ModelChannelConfig] = Field(default=None, description="RAG 向量检索 Embedding 通道")
    mem0_llm: Optional[ModelChannelConfig] = Field(default=None, description="mem0 记忆提取 LLM 通道")
    mem0_embedder: Optional[ModelChannelConfig] = Field(default=None, description="mem0 语义检索 Embedding 通道")


# ============================================================================
# 请求/响应模型
# ============================================================================

class FileUploadResponse(BaseModel):
    """文件上传接口的响应模型"""
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


class ErrorResponse(BaseModel):
    """错误响应模型"""
    error: str = Field(..., description="错误类型")
    message: str = Field(..., description="错误消息")
    details: Optional[dict] = Field(None, description="错误详情")


class ApiConfigValidateRequest(BaseModel):
    """API 配置验证请求"""
    api_key: str = Field(..., description="API Key")
    base_url: str = Field(..., description="API Base URL")
    model: str = Field(..., description="模型名称")
    provider: Optional[str] = Field(default=None, description="服务商标识，用于选择兼容客户端")
    integration: Optional[str] = Field(default=None, description="LangChain 集成方式")
    kind: Literal["chat", "embedding"] = Field(default="chat", description="模型类型")
    dimensions: Optional[int] = Field(
        default=None,
        ge=1,
        le=16_000,
        strict=True,
        description="Embedding 输出维度",
    )
