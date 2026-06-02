"""
项目经历重写助手相关的请求/响应模型
"""

from typing import List, Optional

from pydantic import BaseModel, Field

from app.schemas.schemas import ApiConfig


# ============================================================================
# 请求模型
# ============================================================================


class ProjectRewriteRequest(BaseModel):
    """项目经历重写请求"""
    project_content: str = Field(..., description="原始项目内容")
    project_title: str = Field(..., description="项目标题")
    rewrite_mode: str = Field(..., description="重写模式: star_rewrite/quantify_results/jd_customize/followup_prediction")
    job_description: Optional[str] = Field(default=None, description="目标岗位描述（jd_customize 模式必填）")
    material_id: Optional[int] = Field(default=None, description="关联的素材 ID")
    user_id: Optional[str] = Field(default=None, description="用户标识")
    api_config: Optional[ApiConfig] = Field(default=None, description="用户自定义 API 配置")


# ============================================================================
# 响应/结果模型
# ============================================================================


class ProjectRewriteResult(BaseModel):
    """项目经历重写结果"""
    rewritten_content: str = Field(..., description="重写后的项目文本")
    rewrite_reason: str = Field(..., description="重写原因说明")
    suggested_data_points: List[str] = Field(..., description="建议补充的数据点")
    possible_followup_questions: List[str] = Field(..., description="可能的追问问题")
    should_update_material: bool = Field(..., description="是否建议更新素材库")
    inferred_content: Optional[List[str]] = Field(default=None, description="推断/虚构内容，需标记")


class ProjectRewriteResponse(BaseModel):
    """项目经历重写 API 响应"""
    success: bool = Field(..., description="是否成功")
    result: Optional[ProjectRewriteResult] = Field(default=None, description="重写结果")
    rewrite_id: Optional[int] = Field(default=None, description="数据库记录 ID")
    message: Optional[str] = Field(default=None, description="消息")


class ProjectRewriteHistoryItem(BaseModel):
    """项目经历重写历史项"""
    id: int = Field(..., description="ID")
    project_title: str = Field(..., description="项目标题")
    rewrite_mode: str = Field(..., description="重写模式")
    created_at: str = Field(..., description="创建时间")


class ProjectRewriteHistoryResponse(BaseModel):
    """项目经历重写历史响应"""
    success: bool = Field(..., description="是否成功")
    records: List[ProjectRewriteHistoryItem] = Field(default=[], description="历史记录列表")
    message: Optional[str] = Field(default=None, description="消息")


class ProjectRewriteDetailResponse(BaseModel):
    """项目经历重写详情响应"""
    success: bool = Field(..., description="是否成功")
    record: Optional[dict] = Field(default=None, description="完整记录详情")
    message: Optional[str] = Field(default=None, description="消息")
