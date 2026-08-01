"""用户满意度反馈请求、响应和安全边界模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _SatisfactionBase(BaseModel):
    """禁止未知字段的满意度请求基类。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SatisfactionSubmitRequest(_SatisfactionBase):
    """一次用户满意度提交;星级与说明可空,方面数组按持久化层清洗截断。"""

    agent_type: Literal["interview", "resume_optimize"]
    ref_key: str = Field(min_length=1, max_length=256)
    rating: int | None = Field(default=None, ge=1, le=5)
    satisfied_aspects: list[str] = Field(default_factory=list)
    dissatisfied_aspects: list[str] = Field(default_factory=list)
    comment: str | None = Field(default=None, max_length=2000)


class SatisfactionSubmitResponse(BaseModel):
    """提交结果;created=False 表示幂等命中既有记录。"""

    id: str
    created: bool


class SatisfactionAspectFrequency(BaseModel):
    """一个方面标签及其出现频次。"""

    aspect: str
    count: int


class SatisfactionStatsResponse(BaseModel):
    """满意度全量聚合统计,不含可识别个体信息。"""

    total_count: int
    rating_count: int
    avg_rating: float | None
    rating_distribution: dict[str, int]
    satisfied_frequencies: list[SatisfactionAspectFrequency]
    dissatisfied_frequencies: list[SatisfactionAspectFrequency]
