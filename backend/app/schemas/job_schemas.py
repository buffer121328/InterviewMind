"""
岗位采集与投递相关 Schemas
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# ============================================================================
# 岗位采集
# ============================================================================

class JobCaptureRequest(BaseModel):
    """岗位采集请求"""
    source_url: Optional[str] = Field(default=None, description="岗位链接（优先）")
    job_description: Optional[str] = Field(default=None, description="手动粘贴的 JD 文本")
    platform: str = Field(default="boss", description="平台标识：boss/lagou/linkedin/...")
    company_name_hint: Optional[str] = Field(default=None, description="公司名提示（可选）")
    job_title_hint: Optional[str] = Field(default=None, description="岗位名提示（可选）")
    api_config: Optional[dict] = Field(default=None, description="用户自定义 API 配置")
    cookies: Optional[List[Dict[str, Any]]] = Field(default=None, description="用户登录 Cookies（List[Playwright Cookie Dict]）")
    headless: bool = Field(default=True, description="浏览器是否 headless（无 cookie 时建议 False 让用户完成验证）")


class NormalizedJob(BaseModel):
    """标准化后的岗位信息"""
    company_name: str = Field(default="", description="标准化公司名")
    job_title: str = Field(default="", description="标准化岗位名")
    job_description: str = Field(default="", description="JD 正文")
    salary_text: str = Field(default="", description="薪资文本")
    salary_min: Optional[int] = Field(default=None, description="最低薪资(K)")
    salary_max: Optional[int] = Field(default=None, description="最高薪资(K)")
    city: str = Field(default="", description="城市")
    tags: List[str] = Field(default_factory=list, description="关键词标签")
    source_hash: str = Field(default="", description="去重哈希")


class JobCaptureResponse(BaseModel):
    """岗位采集响应"""
    success: bool = True
    job_id: Optional[int] = None
    normalized_job: Optional[NormalizedJob] = None
    is_duplicate: bool = False
    message: Optional[str] = None


class JobListItem(BaseModel):
    """岗位列表项"""
    id: int
    company_name: str
    job_title: str
    platform: str
    city: str = ""
    salary_text: str = ""
    status: str = "pending"
    tags: List[str] = []
    captured_at: Optional[str] = None


class JobListResponse(BaseModel):
    """岗位列表响应"""
    success: bool = True
    jobs: List[JobListItem] = []
    total: int = 0


class JobDetailResponse(BaseModel):
    """岗位详情响应"""
    success: bool = True
    job: Optional[Dict[str, Any]] = None
    message: Optional[str] = None


# ============================================================================
# 打招呼文案
# ============================================================================

class GreetingGenerateRequest(BaseModel):
    """打招呼文案生成请求"""
    company_name: str = Field(description="目标公司名")
    job_title: str = Field(description="目标岗位名")
    jd_summary: str = Field(default="", description="JD 摘要")
    candidate_highlights: Optional[str] = Field(default=None, description="候选人亮点摘要")
    custom_resume_summary: Optional[str] = Field(default=None, description="定制简历摘要")
    api_config: Optional[Dict[str, Any]] = Field(default=None, description="API 配置")


class GreetingItem(BaseModel):
    """单条打招呼文案"""
    tone: str = Field(description="风格: professional/technical/result_oriented")
    message_text: str = Field(description="文案正文")
    highlights_used: List[str] = Field(default_factory=list, description="使用的亮点")
    risk_notes: str = Field(default="", description="风险提示")


class GreetingGenerateResponse(BaseModel):
    """打招呼文案生成响应"""
    success: bool = True
    greetings: List[GreetingItem] = []
    message: Optional[str] = None


# ============================================================================
# 资产生成
# ============================================================================

class AssetGenerateRequest(BaseModel):
    """资产生成请求"""
    job_id: int = Field(description="已采集的岗位 ID")
    resume_content: str = Field(description="候选人基础简历")
    api_config: Optional[Dict[str, Any]] = Field(default=None, description="API 配置")
    include_project_rewrite: bool = Field(default=False, description="是否包含项目改写")
    template_style: str = Field(default="professional", description="简历模板风格")


class AssetPackage(BaseModel):
    """资产生成结果包"""
    job_id: int
    jd_analysis: Optional[Dict[str, Any]] = None         # JD 匹配分析结果
    custom_resume_id: Optional[int] = None                # 生成简历的 ID
    custom_resume_preview: Optional[str] = None            # 简历 Markdown 预览
    greetings: List[GreetingItem] = []                     # 打招呼文案
    risk_flags: List[str] = []                             # 风险标记
    messages: List[str] = []                               # 提示消息


class AssetGenerateResponse(BaseModel):
    """资产生成响应"""
    success: bool = True
    assets: Optional[AssetPackage] = None
    message: Optional[str] = None


# ============================================================================
# 投递操作
# ============================================================================

class ApplyPreviewRequest(BaseModel):
    """投递预览请求"""
    job_id: int = Field(description="岗位 ID")
    greeting_index: int = Field(default=0, description="选择的打招呼文案索引 (0-2)")
    greeting_text: str = Field(min_length=1, max_length=500, description="用户选定并将要发送的文案")
    resume_id: Optional[int] = Field(default=None, description="定制简历 ID")


class ApplySendRequest(BaseModel):
    """确认发送请求"""
    job_id: int
    greeting_index: int = 0
    greeting_text: str = Field(min_length=1, max_length=500)
    resume_id: Optional[int] = None
    approval_token: str = Field(min_length=20, description="预览接口签发的一次性许可")
    confirmed: bool = Field(default=False, description="用户已明确确认当前预览")


class ApplyResponse(BaseModel):
    """投递操作响应"""
    success: bool = True
    message: Optional[str] = None
    screenshot_path: Optional[str] = None
    screenshot_base64: Optional[str] = None
    send_status: str = "pending"  # pending/sent/failed/manual_takeover/login_required/unavailable
    send_ready: bool = False
    approval_token: Optional[str] = None
    approval_expires_in: Optional[int] = None
    error: Optional[str] = None


# ============================================================================
# 批量推荐页采集（BOSS 半自动化）
# ============================================================================

class CaptureRecommendationsRequest(BaseModel):
    """批量抓取 BOSS 推荐页前 N 个岗位并生成投递资产"""
    query: str = Field(default="", description="搜索关键词（用于过滤推荐结果，可空）")
    resume_content: str = Field(..., description="候选人基础简历")
    city: Optional[str] = Field(default=None, description="可选城市名（目前 BOSS 按 IP 自动定位，仅作提示）")
    top_n: int = Field(default=5, ge=1, le=10, description="抓取前 N 个岗位")
    user_id: Optional[str] = Field(default=None, description="用户标识")
    api_config: Optional[dict] = Field(default=None, description="用户自定义 API 配置")


class CapturedJobSummary(BaseModel):
    """批量采集结果中的单个岗位摘要"""
    job_id: int = Field(..., description="写入 captured_jobs 表的 ID")
    company_name: str = Field(default="", description="公司名")
    job_title: str = Field(default="", description="岗位名")
    salary_text: str = Field(default="", description="薪资文本")
    city: str = Field(default="", description="城市")
    match_score: Optional[float] = Field(default=None, description="JD 匹配度 (0-100)")
    custom_resume_id: Optional[int] = Field(default=None, description="定制简历 ID")
    greetings: List[Dict[str, Any]] = Field(default_factory=list, description="3 条打招呼文案")
    risk_flags: List[str] = Field(default_factory=list, description="风险标记")
    asset_run_id: Optional[str] = Field(default=None, description="统一任务中心中的资产任务 ID")
    asset_status: Optional[str] = Field(default=None, description="资产任务状态")


class CaptureRecommendationsResponse(BaseModel):
    """批量采集响应"""
    success: bool = Field(..., description="是否成功")
    total: int = Field(default=0, description="实际抓取的岗位数")
    jobs: List[CapturedJobSummary] = Field(default_factory=list, description="岗位摘要列表")
    message: Optional[str] = Field(default=None, description="附加消息（如反爬提示）")
