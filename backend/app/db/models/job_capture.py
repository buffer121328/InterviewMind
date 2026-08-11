"""
岗位采集模型 — captured_jobs 表

记录从各平台（BOSS直聘、猎聘等）采集的原始岗位信息，
标准化后作为后续 JD 分析、定制简历生成的输入。
"""

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, JSON, Float,
    Index, func
)
from app.db.models.base import Base


class CapturedJobModel(Base):
    """岗位采集记录"""
    __tablename__ = "captured_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False)

    # 平台信息
    platform = Column(String, nullable=False, default="boss")
    external_job_id = Column(String, nullable=True)  # 平台侧岗位ID

    # 来源
    source_url = Column(String, nullable=True)  # 岗位链接
    source_text = Column(Text, nullable=True)   # 原始抓取/粘贴文本

    # 标准化后字段
    company_name = Column(String, nullable=True)
    company_size_text = Column(String, nullable=True)
    job_title = Column(String, nullable=True)
    job_description = Column(Text, nullable=True)
    salary_text = Column(String, nullable=True)
    salary_min = Column(Integer, nullable=True)
    salary_max = Column(Integer, nullable=True)
    city = Column(String, nullable=True)

    # 标签与元数据
    tags = Column(JSON, nullable=True, default=list)       # ["Java", "Spring", "微服务"]
    match_score = Column(Float, nullable=True)
    asset_run_id = Column(String, nullable=True)
    asset_status = Column(String, nullable=True)
    asset_payload = Column(JSON, nullable=True)
    source_hash = Column(String, nullable=False, index=True)  # 去重标识

    # 状态
    status = Column(String, nullable=False, default="pending")  # 说明：pending/.../applying/applied/manual_takeover

    # 时间
    captured_at = Column(DateTime, nullable=False, server_default=func.now())
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_captured_jobs_user", "user_id", "created_at"),
        Index("idx_captured_jobs_platform", "platform", "user_id"),
        Index("idx_captured_jobs_hash_user", "source_hash", "user_id", unique=True),
        Index("idx_captured_jobs_asset_run", "asset_run_id"),
    )

    def to_dict(self) -> dict:
        """将持久化对象转换为稳定的字典表示，供 API 或审计边界使用；不改变对象状态，也不主动暴露未声明的敏感字段。"""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "platform": self.platform,
            "external_job_id": self.external_job_id,
            "source_url": self.source_url,
            "source_text": self.source_text,
            "company_name": self.company_name,
            "company_size_text": self.company_size_text,
            "job_title": self.job_title,
            "job_description": self.job_description,
            "salary_text": self.salary_text,
            "salary_min": self.salary_min,
            "salary_max": self.salary_max,
            "city": self.city,
            "tags": self.tags or [],
            "match_score": self.match_score,
            "asset_run_id": self.asset_run_id,
            "asset_status": self.asset_status,
            "asset_payload": self.asset_payload or {},
            "source_hash": self.source_hash,
            "status": self.status,
            "captured_at": self.captured_at.isoformat() if self.captured_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
