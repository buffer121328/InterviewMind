"""
岗位采集与投递相关 Schemas
"""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from integrations.boss.security import (
    is_allowed_boss_job_url,
    is_allowed_boss_search_url,
)

class JobListItem(BaseModel):
    """岗位列表项"""
    id: int
    company_name: str
    company_size_text: str = ""
    job_title: str
    platform: str
    city: str = ""
    salary_text: str = ""
    source_url: str = ""
    match_score: Optional[float] = None
    asset_run_id: Optional[str] = None
    asset_status: Optional[str] = None
    status: str = "pending"
    tags: List[str] = Field(default_factory=list)
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


class GreetingItem(BaseModel):
    """单条打招呼文案"""
    tone: str = Field(description="风格: professional/technical/result_oriented")
    message_text: str = Field(description="文案正文")
    highlights_used: List[str] = Field(default_factory=list, description="使用的亮点")
    risk_notes: str = Field(default="", description="风险提示")


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
    greetings: List[GreetingItem] = Field(default_factory=list)  # 打招呼文案
    risk_flags: List[str] = Field(default_factory=list)          # 风险标记
    messages: List[str] = Field(default_factory=list)            # 提示消息


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

    success: bool = True
    total: int = 0
    duplicates: int = 0
    jobs: List[Dict[str, Any]] = Field(default_factory=list)
    failed: List[JobImportFailedItem] = Field(default_factory=list)
    message: str = ""


class BossTabStatusResponse(BaseModel):
    """现有 Edge/Chrome BOSS 标签页的有限连接状态。"""

    success: bool = True
    browser_channel: Literal["msedge", "chrome"]
    browser_label: str
    connected: bool
    current_url: str = ""
    page_status: str
    ready_state: str = ""
    visible_card_count: int = Field(default=0, ge=0, le=20)
    message: str


class BossTabCaptureRequest(BaseModel):
    """请求后端复用现有浏览器 BOSS 标签页执行一次保守搜索与采集。"""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=200, description="写入现有 BOSS 标签页的搜索关键词")
    city: Optional[str] = Field(default=None, max_length=20, description="城市代码；留空时复用当前标签页城市")
    max_cards: int = Field(default=20, ge=1, le=20, description="单次最多读取的候选岗位卡片数")
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

    success: bool = True
    browser_channel: Literal["msedge", "chrome"]
    browser_label: str
    message: str
    kind: Literal["interviewmind-boss-dom-capture-v1"]
    source_page_url: str
    captured_at: str
    page_status: str
    ready_state: str = ""
    cards: List[BossDomJobCard] = Field(min_length=1, max_length=20)

    @field_validator("source_page_url")
    @classmethod
    def validate_source_page_url(cls, value: str) -> str:
        """确保浏览器桥接只回传 BOSS 官方岗位搜索页。"""
        if not is_allowed_boss_search_url(value):
            raise ValueError("仅允许返回 BOSS 官方岗位搜索页")
        return value


class GreetingUpdateRequest(BaseModel):
    """Edit one persisted greeting option in a generated asset package."""

    message_text: str = Field(min_length=20, max_length=500)


class JobExportApplicationRequest(BaseModel):
    """Export a captured job and one editable greeting into application tracking."""

    greeting_index: int = Field(default=0, ge=0, le=2)
    greeting_text: str = Field(min_length=20, max_length=500)


class BossOpenJobRequest(BaseModel):
    """Open one persisted official job URL in the existing logged-in browser tab."""

    browser_channel: Optional[Literal["msedge", "chrome"]] = None


class CaptureRecommendationsRequest(BaseModel):
    """导入用户当前 BOSS 搜索页的有限 DOM 卡片并生成投递资产。"""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(default="", max_length=200, description="搜索关键词，仅用于匹配排序")
    resume_content: str = Field(min_length=1, description="候选人基础简历")
    source_page_url: str = Field(min_length=8, max_length=2048, description="用户当前打开的 BOSS 搜索页")
    cards: List[BossDomJobCard] = Field(min_length=1, max_length=20, description="当前页提取的岗位卡片，最多 20 张")
    city: Optional[str] = Field(default=None, max_length=100, description="城市提示，仅用于结果补全")
    top_n: int = Field(default=3, ge=1, le=20, description="导入前 N 个岗位，最多 20 个")
    api_config: Optional[dict] = Field(default=None, description="用户自定义 API 配置")

    @field_validator("source_page_url")
    @classmethod
    def validate_source_page_url(cls, value: str) -> str:
        """只接受 BOSS 官方搜索页，登录态和 Cookie 不进入请求。"""
        if not is_allowed_boss_search_url(value):
            raise ValueError("仅允许导入 BOSS 官方岗位搜索页")
        return value
