"""
JD 匹配分析相关的请求/响应模型
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from app.schemas.schemas import ApiConfig


# ============================================================================
# 请求模型
# ============================================================================

class JDMatchRequest(BaseModel):
    """JD 匹配分析请求"""
    resume_content: str = Field(..., description="简历内容")
    job_description: str = Field(..., description="目标职位描述")
    user_id: Optional[str] = Field(default=None, description="用户标识")
    resume_source_type: str = Field(default="manual_input", description="简历来源: uploaded_resume / generated_resume / manual_input")
    resume_source_id: Optional[int] = Field(default=None, description="来源对象 ID")
    api_config: Optional[ApiConfig] = Field(default=None, description="用户自定义 API 配置")


# ============================================================================
# 结果模型
# ============================================================================

class JDMatchResult(BaseModel):
    """JD 匹配分析结果"""
    overall_match_score: float = Field(..., ge=0, le=100, description="综合匹配分 (0-100)")
    skill_match_score: float = Field(..., ge=0, le=100, description="技能匹配分 (0-100)")
    project_match_score: float = Field(..., ge=0, le=100, description="项目匹配分 (0-100)")
    experience_match_score: float = Field(..., ge=0, le=100, description="经验匹配分 (0-100)")
    education_match_score: float = Field(..., ge=0, le=100, description="教育匹配分 (0-100)")
    matched_keywords: List[str] = Field(default=[], description="命中关键词")
    missing_keywords: List[str] = Field(default=[], description="缺失关键词")
    strengths: List[str] = Field(default=[], description="优势")
    risks: List[str] = Field(default=[], description="风险")
    priority_actions: List[str] = Field(default=[], description="优先改进建议")
    selection_hints: Optional[Dict[str, Any]] = Field(default=None, description="素材筛选/项目改写方向提示")


# ============================================================================
# API 响应包装
# ============================================================================

class JDMatchResponse(BaseModel):
    """JD 匹配分析 API 响应"""
    success: bool = Field(..., description="是否成功")
    result: Optional[JDMatchResult] = Field(default=None, description="分析结果")
    analysis_id: Optional[int] = Field(default=None, description="分析结果 ID（用于后续查询）")
    message: Optional[str] = Field(default=None, description="消息")


class JDMatchHistoryItem(BaseModel):
    """JD 匹配分析历史记录项"""
    id: int = Field(..., description="ID")
    resume_source_type: str = Field(..., description="简历来源类型")
    resume_source_id: Optional[int] = Field(default=None, description="来源对象 ID")
    job_description: str = Field(..., description="目标职位描述")
    created_at: str = Field(..., description="创建时间")


class JDMatchHistoryResponse(BaseModel):
    """JD 匹配分析历史列表响应"""
    success: bool = Field(..., description="是否成功")
    results: List[JDMatchHistoryItem] = Field(default=[], description="历史记录")
    message: Optional[str] = Field(default=None, description="消息")


class JDMatchDetailResponse(BaseModel):
    """JD 匹配分析详情响应"""
    success: bool = Field(..., description="是否成功")
    result: Optional[Dict[str, Any]] = Field(default=None, description="完整分析结果")
    message: Optional[str] = Field(default=None, description="消息")
