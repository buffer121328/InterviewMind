"""用户满意度反馈请求、响应和安全边界模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.evaluation.evaluations import ProductionHistoryConfirmRequest


class _SatisfactionBase(BaseModel):
    """禁止未知字段的满意度请求基类。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SatisfactionSubmitRequest(_SatisfactionBase):
    """一次用户满意度提交;星级与说明可空,方面数组按持久化层清洗截断。"""

    agent_type: Literal["interview", "resume_optimize"] = Field(description="反馈主体类型")
    ref_key: str = Field(min_length=1, max_length=256, description="关联业务记录键")
    rating: int | None = Field(default=None, ge=1, le=5, description="星级评分")
    satisfied_aspects: list[str] = Field(default_factory=list, description="满意的方面")
    dissatisfied_aspects: list[str] = Field(default_factory=list, description="不满意的方面")
    comment: str | None = Field(default=None, max_length=2000, description="评论文本")


class SatisfactionSubmitResponse(BaseModel):
    """提交结果;created=False 表示幂等命中既有记录。"""

    id: str = Field(description="反馈记录 ID")
    created: bool = Field(description="是否新建记录")


class SatisfactionAspectFrequency(BaseModel):
    """一个方面标签及其出现频次。"""

    aspect: str = Field(description="方面标签")
    count: int = Field(description="出现频次")


class SatisfactionStatsResponse(BaseModel):
    """满意度全量聚合统计,不含可识别个体信息。"""

    total_count: int = Field(description="反馈总数")
    rating_count: int = Field(description="含星级评分的反馈数")
    avg_rating: float | None = Field(default=None, description="平均评分")
    rating_distribution: dict[str, int] = Field(description="星级分布")
    satisfied_frequencies: list[SatisfactionAspectFrequency] = Field(description="满意方面频次")
    dissatisfied_frequencies: list[SatisfactionAspectFrequency] = Field(
        description="不满意方面频次"
    )


class SatisfactionFeedbackItem(BaseModel):
    """一条 owner 可见、已脱敏的反馈治理记录。"""

    id: str
    agent_type: Literal["interview", "resume_optimize"]
    ref_key: str
    rating: int | None
    satisfied_aspects: list[str]
    dissatisfied_aspects: list[str]
    comment: str | None
    source_verified: bool
    review_status: Literal["not_required", "pending", "resolved", "promoted"]
    review_note: str | None
    candidate_dataset_id: str | None
    created_at: datetime


class SatisfactionFeedbackListResponse(BaseModel):
    items: list[SatisfactionFeedbackItem]
    total: int
    page: int
    limit: int


class SatisfactionReviewRequest(_SatisfactionBase):
    status: Literal["resolved"] = "resolved"
    note: str = Field(min_length=1, max_length=2000)


class SatisfactionPromotionLinkRequest(_SatisfactionBase):
    dataset_id: str = Field(min_length=1, max_length=160)
    capability: Literal["interview_planner", "resume_optimizer"]


class SatisfactionPromotionRequest(_SatisfactionBase):
    capability: Literal["interview_planner", "resume_optimizer"]
    confirmation: ProductionHistoryConfirmRequest
