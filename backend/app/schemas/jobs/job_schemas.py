"""
岗位采集与投递相关 Schemas
"""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.schemas import ApiConfig

from integrations.boss.security import (
    is_allowed_boss_job_url,
    is_allowed_boss_search_url,
)

class JobListItem(BaseModel):
    """岗位列表项"""
    id: int = Field(..., description="岗位 ID")
    company_name: str = Field(..., description="公司名称")
    company_size_text: str = Field("", description="公司规模文本")
    job_title: str = Field(..., description="岗位名称")
    platform: str = Field(..., description="来源平台")
    city: str = Field("", description="城市")
    salary_text: str = Field("", description="薪资文本")
    source_url: str = Field("", description="来源链接")
    match_score: Optional[float] = Field(None, description="匹配度")
    asset_run_id: Optional[str] = Field(None, description="资产生成运行 ID")
    asset_status: Optional[str] = Field(None, description="资产生成状态")
    status: str = Field("pending", description="状态")
    tags: List[str] = Field(default_factory=list, description="标签")
    captured_at: Optional[str] = Field(None, description="采集时间")


class JobListResponse(BaseModel):
    """岗位列表响应"""
    success: bool = Field(True, description="是否成功")
    jobs: List[JobListItem] = Field(default_factory=list, description="岗位列表")
    total: int = Field(0, description="岗位总数")


class JobDetailResponse(BaseModel):
    """岗位详情响应"""
    success: bool = Field(True, description="是否成功")
    job: Optional[Dict[str, Any]] = Field(None, description="岗位详情数据")
    message: Optional[str] = Field(None, description="提示消息")


class JobJdAnalysisRequest(BaseModel):
    """对已入库岗位显式执行 JD 匹配分析的受控输入。"""

    resume_content: str = Field(min_length=1, max_length=50_000, description="当前候选人简历文本")
    api_config: Optional[ApiConfig] = Field(default=None, description="请求级模型配置")


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
    job_id: int = Field(..., description="关联的岗位 ID")
    jd_analysis: Optional[Dict[str, Any]] = Field(default=None, description="JD 匹配分析结果")
    custom_resume_id: Optional[int] = Field(default=None, description="生成简历的 ID")
    custom_resume_preview: Optional[str] = Field(default=None, description="简历 Markdown 预览")
    risk_flags: List[str] = Field(default_factory=list, description="风险标记")
    messages: List[str] = Field(default_factory=list, description="提示消息")


# ============================================================================
# BOSS 现有标签页 DOM 导入
# ============================================================================


class BossDomJobCard(BaseModel):
    """现有已登录 BOSS 标签页桥接提取的一张有限字段岗位卡片。"""

    model_config = ConfigDict(extra="forbid")

    company_name: str = Field(default="", max_length=200)
    company_size_text: str = Field(default="", max_length=100)
    job_title: str = Field(min_length=1, max_length=200)
    salary_text: str = Field(default="", max_length=100)
    city: str = Field(default="", max_length=100)
    title_summary: str = Field(default="", max_length=300)
    job_description: str = Field(min_length=8, max_length=3000)
    source_url: str = Field(min_length=8, max_length=2048)
    preliminary_match_score: Optional[float] = Field(
        default=None,
        ge=0,
        le=100,
        description="采集阶段排序产生的展示用匹配度；入库时仅作记录，不赋予治理语义",
    )

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        """拒绝外部域名和非岗位详情链接，避免 DOM 导入被转成任意 URL 入口。"""
        if not is_allowed_boss_job_url(value):
            raise ValueError("岗位卡片仅允许 BOSS 官方岗位详情链接")
        return value


class JobLibraryImportRequest(BaseModel):
    """把用户确认的待入库卡片确定性写入岗位库，不触发模型或后台任务。"""

    model_config = ConfigDict(extra="forbid")

    cards: List[BossDomJobCard] = Field(
        min_length=1,
        max_length=20,
        description="采集阶段排序后的待入库卡片，顺序即匹配度顺序",
    )
    city: Optional[str] = Field(default=None, max_length=20, description="城市代码提示")


class JobImportFailedItem(BaseModel):
    """一键入库中单张卡片保存失败的安全明细。"""

    company_name: str = ""
    job_title: str = ""
    reason: str = ""
    source_url: str = ""


class JobImportResponse(BaseModel):
    """一键入库结果：成功保存的岗位与失败明细。"""

    success: bool = Field(True, description="是否成功")
    total: int = Field(0, description="本次导入的岗位总数")
    duplicates: int = Field(0, description="重复跳过数量")
    jobs: List[Dict[str, Any]] = Field(default_factory=list, description="成功保存的岗位")
    failed: List[JobImportFailedItem] = Field(default_factory=list, description="失败明细")
    message: str = Field("", description="结果提示消息")


class BossTabStatusResponse(BaseModel):
    """现有 Edge/Chrome BOSS 标签页的有限连接状态。"""

    success: bool = Field(True, description="是否成功")
    browser_channel: Literal["msedge", "chrome"] = Field(..., description="浏览器渠道")
    browser_label: str = Field(..., description="浏览器显示名称")
    connected: bool = Field(..., description="是否已连接")
    current_url: str = Field("", description="当前标签页 URL")
    page_status: str = Field(..., description="页面状态")
    ready_state: str = Field("", description="页面加载状态")
    visible_card_count: int = Field(default=0, ge=0, le=20, description="可见岗位卡片数")
    message: str = Field(..., description="提示消息")


class BossTabCaptureRequest(BaseModel):
    """请求后端复用现有浏览器 BOSS 标签页执行一次保守搜索与采集。"""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=200, description="写入现有 BOSS 标签页的搜索关键词")
    city: Optional[str] = Field(default=None, max_length=20, description="城市代码；留空时复用当前标签页城市")
    max_cards: int = Field(default=20, ge=1, le=20, description="单次最多读取的候选岗位卡片数")
    experience: Literal["any", "no_experience", "experience_unlimited", "one_to_three"] = Field(
        default="any",
        description="受控工作经验筛选：不限、无经验、经验不限或 1–3 年",
    )
    job_type: Literal["full_time"] = Field(default="full_time", description="当前固定为全职")
    browser_channel: Optional[Literal["msedge", "chrome"]] = Field(
        default=None,
        description="现有浏览器渠道；留空时使用 BOSS_BROWSER_CHANNEL",
    )

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        """去除首尾空白并拒绝空关键词，避免无意导航到宽泛岗位列表。"""
        normalized = value.strip()
        if not normalized:
            raise ValueError("搜索关键词不能为空")
        return normalized

    @field_validator("city")
    @classmethod
    def validate_city(cls, value: Optional[str]) -> Optional[str]:
        """城市仅接受 BOSS 数字代码；空值表示继续使用已打开页面的城市。"""
        normalized = str(value or "").strip()
        if not normalized:
            return None
        if not normalized.isdigit():
            raise ValueError("BOSS 城市必须填写数字城市代码")
        return normalized


class BossTabCaptureResponse(BaseModel):
    """从现有登录标签页返回的有限字段岗位数据，不包含 Cookie 或整页 HTML。"""

    success: bool = Field(True, description="是否成功")
    browser_channel: Literal["msedge", "chrome"] = Field(..., description="浏览器渠道")
    browser_label: str = Field(..., description="浏览器显示名称")
    message: str = Field(..., description="提示消息")
    kind: Literal["interviewmind-boss-dom-capture-v1"] = Field(..., description="数据协议类型")
    source_page_url: str = Field(..., description="来源页面 URL")
    captured_at: str = Field(..., description="采集时间")
    page_status: str = Field(..., description="页面状态")
    ready_state: str = Field("", description="页面加载状态")
    cards: List[BossDomJobCard] = Field(min_length=1, max_length=20, description="采集到的岗位卡片")
    detail_enriched_count: int = Field(default=0, ge=0, le=20, description="详情补全卡片数")
    detail_fallback_count: int = Field(default=0, ge=0, le=20, description="详情回退卡片数")

    @field_validator("source_page_url")
    @classmethod
    def validate_source_page_url(cls, value: str) -> str:
        """确保浏览器桥接只回传 BOSS 官方岗位搜索页。"""
        if not is_allowed_boss_search_url(value):
            raise ValueError("仅允许返回 BOSS 官方岗位搜索页")
        return value


class BossOpenJobRequest(BaseModel):
    """请求在现有浏览器标签页打开某个岗位详情的请求（可指定浏览器渠道）。"""

    browser_channel: Optional[Literal["msedge", "chrome"]] = Field(
        default=None,
        description="浏览器渠道；留空时使用默认渠道",
    )


class CaptureRecommendationsRequest(BaseModel):
    """导入用户当前 BOSS 搜索页的有限 DOM 卡片并生成投递资产。"""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(default="", max_length=200, description="搜索关键词，仅用于匹配排序")
    resume_content: str = Field(min_length=1, description="候选人基础简历")
    source_page_url: str = Field(min_length=8, max_length=2048, description="用户当前打开的 BOSS 搜索页")
    cards: List[BossDomJobCard] = Field(min_length=1, max_length=20, description="当前页提取的岗位卡片，最多 20 张")
    city: Optional[str] = Field(default=None, max_length=100, description="城市提示，仅用于结果补全")
    experience: Literal["any", "no_experience", "experience_unlimited", "one_to_three"] = Field(
        default="any",
        description="本次已应用的受控工作经验筛选；无经验会额外校验完整 JD",
    )
    top_n: int = Field(default=3, ge=1, le=20, description="导入前 N 个岗位，最多 20 个")
    api_config: Optional[dict] = Field(default=None, description="用户自定义 API 配置")

    @field_validator("source_page_url")
    @classmethod
    def validate_source_page_url(cls, value: str) -> str:
        """只接受 BOSS 官方搜索页，登录态和 Cookie 不进入请求。"""
        if not is_allowed_boss_search_url(value):
            raise ValueError("仅允许导入 BOSS 官方岗位搜索页")
        return value
