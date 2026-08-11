"""
投递追踪数据模型
定义岗位投递记录和事件流水的数据结构
"""

from typing import List, Literal, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


# ============================================================================
# 枚举常量
# ============================================================================

# 投递状态枚举
APPLICATION_STATUSES = ['saved', 'applied', 'interview', 'offer', 'rejected', 'accepted']

# 事件类型枚举
EVENT_TYPES = [
    'saved', 'applied', 'phone_screen', 'technical', 'behavioral',
    'final', 'offer', 'rejected', 'accepted', 'note'
]

# 优先级枚举
PRIORITIES = ['high', 'medium', 'low']


# ============================================================================
# 数据库行模型（对应表结构）
# ============================================================================

class JobApplicationRow(BaseModel):
    """岗位投递记录（数据库行）"""
    id: int
    user_id: str
    company_name: str
    job_title: str
    job_description: Optional[str] = None
    channel: Optional[str] = None
    generated_resume_id: Optional[int] = None
    latest_status: str = 'saved'
    priority: str = 'medium'
    notes: Optional[str] = None
    source_platform: Optional[str] = None
    source_url: Optional[str] = None
    external_job_id: Optional[str] = None
    captured_job_id: Optional[int] = None
    greeting_text: Optional[str] = None
    send_status: Optional[str] = None
    custom_resume_id: Optional[int] = None
    created_at: str
    updated_at: str


class ApplicationEventRow(BaseModel):
    """投递事件记录（数据库行）"""
    id: int
    application_id: int
    event_type: str
    event_time: str
    event_data: Dict[str, Any] = {}
    created_at: str


# ============================================================================
# API 请求模型
# ============================================================================

class ApplicationCreateRequest(BaseModel):
    """创建投递记录请求"""
    company_name: str = Field(..., min_length=1, max_length=200, description="公司名称")
    job_title: str = Field(..., min_length=1, max_length=200, description="岗位名称")
    job_description: Optional[str] = Field(None, description="岗位描述 (JD)")
    channel: Optional[str] = Field(None, max_length=100, description="投递渠道")
    latest_status: Optional[str] = Field('saved', description="初始状态")
    priority: Optional[str] = Field('medium', description="优先级")
    notes: Optional[str] = Field(None, description="备注")
    source_platform: Optional[str] = Field(None, max_length=50)
    source_url: Optional[str] = Field(None, max_length=2048)
    external_job_id: Optional[str] = Field(None, max_length=200)
    captured_job_id: Optional[int] = None
    greeting_text: Optional[str] = Field(None, max_length=800)
    send_status: Optional[str] = Field(None, max_length=50)


class ApplicationUpdateRequest(BaseModel):
    """更新投递记录请求"""
    company_name: Optional[str] = Field(None, min_length=1, max_length=200, description="公司名称")
    job_title: Optional[str] = Field(None, min_length=1, max_length=200, description="岗位名称")
    job_description: Optional[str] = Field(None, description="岗位描述")
    channel: Optional[str] = Field(None, max_length=100, description="投递渠道")
    latest_status: Optional[str] = Field(None, description="当前状态")
    priority: Optional[str] = Field(None, description="优先级")
    notes: Optional[str] = Field(None, description="备注")
    greeting_text: Optional[str] = Field(None, max_length=800)
    send_status: Optional[Literal["pending", "sending", "sent", "failed", "unknown"]] = None


class EventCreateRequest(BaseModel):
    """创建事件请求"""
    event_type: str = Field(..., description="事件类型")
    event_time: Optional[str] = Field(None, description="事件时间（默认当前时间）")
    event_data: Optional[Dict[str, Any]] = Field(default_factory=dict, description="事件附加数据")


class ApplicationResumeLinkRequest(BaseModel):
    """定义投递简历链接请求相关后端数据结构或服务组件。"""

    resume_id: Optional[int] = Field(default=None, ge=1, description="生成简历 ID；null 表示解除关联")


class LinkedResumeAsset(BaseModel):
    """定义关联简历资产相关后端数据结构或服务组件。"""

    id: int
    title: str
    job_description: Optional[str] = None
    content: str
    created_at: str


# ============================================================================
# API 响应模型
# ============================================================================

class ApplicationListItem(BaseModel):
    """投递列表项（简化版）"""
    id: int
    company_name: str
    job_title: str
    channel: Optional[str] = None
    generated_resume_id: Optional[int] = None
    latest_status: str
    priority: str
    notes: Optional[str] = None
    source_platform: Optional[str] = None
    source_url: Optional[str] = None
    captured_job_id: Optional[int] = None
    greeting_text: Optional[str] = None
    send_status: Optional[str] = None
    custom_resume_id: Optional[int] = None
    created_at: str
    updated_at: str


class ApplicationDetail(BaseModel):
    """投递详情（含事件列表）"""
    id: int
    user_id: str
    company_name: str
    job_title: str
    job_description: Optional[str] = None
    channel: Optional[str] = None
    generated_resume_id: Optional[int] = None
    latest_status: str
    priority: str
    notes: Optional[str] = None
    source_platform: Optional[str] = None
    source_url: Optional[str] = None
    external_job_id: Optional[str] = None
    captured_job_id: Optional[int] = None
    greeting_text: Optional[str] = None
    send_status: Optional[str] = None
    custom_resume_id: Optional[int] = None
    linked_resume: Optional[LinkedResumeAsset] = None
    created_at: str
    updated_at: str
    events: List[ApplicationEventRow] = Field(default_factory=list, description="事件流水")


class ApplicationListResponse(BaseModel):
    """投递列表响应"""
    success: bool
    applications: List[ApplicationListItem] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0


class ApplicationDetailResponse(BaseModel):
    """投递详情响应"""
    success: bool
    application: ApplicationDetail


class EventListResponse(BaseModel):
    """事件列表响应"""
    success: bool
    events: List[ApplicationEventRow] = Field(default_factory=list)
