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
    id: int = Field(..., description="主键 ID")
    user_id: str = Field(..., description="用户 ID")
    company_name: str = Field(..., description="公司名称")
    job_title: str = Field(..., description="岗位名称")
    job_description: Optional[str] = Field(None, description="岗位描述 (JD)")
    channel: Optional[str] = Field(None, description="投递渠道")
    generated_resume_id: Optional[int] = Field(None, description="生成简历 ID")
    latest_status: str = Field('saved', description="最新状态")
    priority: str = Field('medium', description="优先级")
    notes: Optional[str] = Field(None, description="备注")
    source_platform: Optional[str] = Field(None, description="来源平台")
    source_url: Optional[str] = Field(None, description="来源链接")
    external_job_id: Optional[str] = Field(None, description="外部平台岗位 ID")
    captured_job_id: Optional[int] = Field(None, description="采集任务 ID")
    custom_resume_id: Optional[int] = Field(None, description="自定义简历 ID")
    created_at: str = Field(..., description="创建时间")
    updated_at: str = Field(..., description="更新时间")


class ApplicationEventRow(BaseModel):
    """投递事件记录（数据库行）"""
    id: int = Field(..., description="主键 ID")
    application_id: int = Field(..., description="投递记录 ID")
    event_type: str = Field(..., description="事件类型")
    event_time: str = Field(..., description="事件时间")
    event_data: Dict[str, Any] = Field(default_factory=dict, description="事件附加数据")
    created_at: str = Field(..., description="创建时间")


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
    source_platform: Optional[str] = Field(None, max_length=50, description="来源平台")
    source_url: Optional[str] = Field(None, max_length=2048, description="来源链接")
    external_job_id: Optional[str] = Field(None, max_length=200, description="外部平台岗位 ID")
    captured_job_id: Optional[int] = Field(None, description="采集任务 ID")


class ApplicationUpdateRequest(BaseModel):
    """更新投递记录请求"""
    company_name: Optional[str] = Field(None, min_length=1, max_length=200, description="公司名称")
    job_title: Optional[str] = Field(None, min_length=1, max_length=200, description="岗位名称")
    job_description: Optional[str] = Field(None, description="岗位描述")
    channel: Optional[str] = Field(None, max_length=100, description="投递渠道")
    latest_status: Optional[str] = Field(None, description="当前状态")
    priority: Optional[str] = Field(None, description="优先级")
    notes: Optional[str] = Field(None, description="备注")


class EventCreateRequest(BaseModel):
    """创建事件请求"""
    event_type: str = Field(..., description="事件类型")
    event_time: Optional[str] = Field(None, description="事件时间（默认当前时间）")
    event_data: Optional[Dict[str, Any]] = Field(default_factory=dict, description="事件附加数据")


class ApplicationResumeLinkRequest(BaseModel):
    """绑定或解绑生成简历到投递记录的请求；resume_id 为 null 表示解绑。"""

    resume_id: Optional[int] = Field(default=None, ge=1, description="生成简历 ID；null 表示解除关联")


class LinkedResumeAsset(BaseModel):
    """与投递记录关联的生成简历资产。"""

    id: int = Field(..., description="简历资产 ID")
    title: str = Field(..., description="简历标题")
    job_description: Optional[str] = Field(None, description="关联岗位描述 (JD)")
    content: str = Field(..., description="简历内容")
    created_at: str = Field(..., description="创建时间")


# ============================================================================
# API 响应模型
# ============================================================================

class ApplicationListItem(BaseModel):
    """投递列表项（简化版）"""
    id: int = Field(..., description="主键 ID")
    company_name: str = Field(..., description="公司名称")
    job_title: str = Field(..., description="岗位名称")
    channel: Optional[str] = Field(None, description="投递渠道")
    generated_resume_id: Optional[int] = Field(None, description="生成简历 ID")
    latest_status: str = Field(..., description="最新状态")
    priority: str = Field(..., description="优先级")
    notes: Optional[str] = Field(None, description="备注")
    source_platform: Optional[str] = Field(None, description="来源平台")
    source_url: Optional[str] = Field(None, description="来源链接")
    captured_job_id: Optional[int] = Field(None, description="采集任务 ID")
    custom_resume_id: Optional[int] = Field(None, description="自定义简历 ID")
    created_at: str = Field(..., description="创建时间")
    updated_at: str = Field(..., description="更新时间")


class ApplicationDetail(BaseModel):
    """投递详情（含事件列表）"""
    id: int = Field(..., description="主键 ID")
    user_id: str = Field(..., description="用户 ID")
    company_name: str = Field(..., description="公司名称")
    job_title: str = Field(..., description="岗位名称")
    job_description: Optional[str] = Field(None, description="岗位描述 (JD)")
    channel: Optional[str] = Field(None, description="投递渠道")
    generated_resume_id: Optional[int] = Field(None, description="生成简历 ID")
    latest_status: str = Field(..., description="最新状态")
    priority: str = Field(..., description="优先级")
    notes: Optional[str] = Field(None, description="备注")
    source_platform: Optional[str] = Field(None, description="来源平台")
    source_url: Optional[str] = Field(None, description="来源链接")
    external_job_id: Optional[str] = Field(None, description="外部平台岗位 ID")
    captured_job_id: Optional[int] = Field(None, description="采集任务 ID")
    custom_resume_id: Optional[int] = Field(None, description="自定义简历 ID")
    linked_resume: Optional[LinkedResumeAsset] = Field(None, description="关联的生成简历资产")
    created_at: str = Field(..., description="创建时间")
    updated_at: str = Field(..., description="更新时间")
    events: List[ApplicationEventRow] = Field(default_factory=list, description="事件流水")


class ApplicationListResponse(BaseModel):
    """投递列表响应"""
    success: bool = Field(..., description="是否成功")
    applications: List[ApplicationListItem] = Field(default_factory=list, description="投递列表")
    total: int = Field(0, description="总数")
    limit: int = Field(50, description="分页大小")
    offset: int = Field(0, description="分页偏移")


class ApplicationDetailResponse(BaseModel):
    """投递详情响应"""
    success: bool = Field(..., description="是否成功")
    application: ApplicationDetail = Field(..., description="投递详情")


class EventListResponse(BaseModel):
    """事件列表响应"""
    success: bool = Field(..., description="是否成功")
    events: List[ApplicationEventRow] = Field(default_factory=list, description="事件列表")
