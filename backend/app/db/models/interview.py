"""
面试相关 SQLAlchemy ORM 模型
对应表: interview_weakness_reports, question_bank_items, question_bank_imports,
question_bank_followups, interview_question_attempts
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class WeaknessReportModel(Base):
    """面试短板报告：每个会话至多一份，保存降级或模型生成的短板 JSON。"""

    __tablename__ = "interview_weakness_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # 自增主键
    user_id: Mapped[str] = mapped_column(String)                                  # 所属用户 ID
    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("sessions.session_id", ondelete="CASCADE"), unique=True
    )  # 关联会话 ID；随会话删除级联删除，且唯一
    series_id: Mapped[str | None] = mapped_column(String, nullable=True)          # 会话系列标识
    report_data: Mapped[dict] = mapped_column(JSONB)                              # 短板报告内容（JSON）
    created_at: Mapped[datetime] = mapped_column(DateTime)                        # 创建时间
    updated_at: Mapped[datetime] = mapped_column(DateTime)                        # 最后更新时间

    __table_args__ = (
        # 按用户+时间查询短板报告
        Index("idx_weakness_report_user", "user_id", "created_at"),
        # 按会话快速定位短板报告
        Index("idx_weakness_report_session", "session_id"),
    )


class QuestionBankItemModel(Base):
    """个人题库主问题：记录来源、难度、优先级与使用统计，供面试选题。"""

    __tablename__ = "question_bank_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # 自增主键
    user_id: Mapped[str] = mapped_column(String)                                  # 所属用户 ID
    source_type: Mapped[str] = mapped_column(String, default="manual")            # 题目来源：manual/report 等
    source_id: Mapped[str | None] = mapped_column(String, nullable=True)          # 来源对象 ID（如报告 ID）
    origin_session_id: Mapped[str | None] = mapped_column(String, nullable=True)  # 来源会话 ID
    question_text: Mapped[str] = mapped_column(Text)                              # 题目正文
    reference_answer: Mapped[str | None] = mapped_column(Text, nullable=True)     # 参考答案
    tags: Mapped[list] = mapped_column(JSONB, default=list)                       # 标签列表
    difficulty: Mapped[str] = mapped_column(String, default="medium")             # 难度：easy/medium/hard
    target_skill: Mapped[str | None] = mapped_column(String, nullable=True)       # 针对技能
    question_type: Mapped[str] = mapped_column(String, default="tech")            # 题型：tech/hr 等
    priority: Mapped[str] = mapped_column(String, default="low", nullable=False)  # 优先级：required/high/low
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)             # 是否已人工核实
    usage_count: Mapped[int] = mapped_column(Integer, default=0)                  # 被使用次数
    created_at: Mapped[datetime] = mapped_column(DateTime)                        # 创建时间
    updated_at: Mapped[datetime] = mapped_column(DateTime)                        # 最后更新时间

    __table_args__ = (
        # 按用户+时间查询题库
        Index("idx_question_bank_user", "user_id", "created_at"),
        # 按题型筛选
        Index("idx_question_bank_type", "question_type"),
        # 按难度筛选
        Index("idx_question_bank_difficulty", "difficulty"),
        # 按核实状态筛选
        Index("idx_question_bank_verified", "is_verified"),
        # 面试选题查询：用户+题型+优先级+使用次数
        Index(
            "idx_question_bank_selection",
            "user_id",
            "question_type",
            "priority",
            "usage_count",
        ),
        # 优先级取值约束
        CheckConstraint(
            "priority IN ('required', 'high', 'low')",
            name="ck_question_bank_priority",
        ),
        # 同一用户、来源、会话下只保留一份题目，避免重复入库
        UniqueConstraint(
            "user_id", "source_type", "source_id", "origin_session_id",
            name="uq_question_bank_report_source",
        ),
    )


class QuestionBankImportModel(Base):
    """题库批量导入任务：记录导入来源、状态与成功/总数。"""

    __tablename__ = "question_bank_imports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # 自增主键
    user_id: Mapped[str] = mapped_column(String)                                  # 所属用户 ID
    import_source: Mapped[str] = mapped_column(String, default="file")            # 导入来源：file 等
    import_status: Mapped[str] = mapped_column(String, default="pending")         # 导入状态：pending/succeeded/failed
    file_name: Mapped[str | None] = mapped_column(String, nullable=True)          # 导入文件名
    total_count: Mapped[int] = mapped_column(Integer, default=0)                  # 待导入总数
    success_count: Mapped[int] = mapped_column(Integer, default=0)                # 成功导入数
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)              # 导入结果摘要
    created_at: Mapped[datetime] = mapped_column(DateTime)                        # 创建时间

    __table_args__ = (
        # 按用户+时间查询导入记录
        Index("idx_question_bank_imports_user", "user_id", "created_at"),
    )


class QuestionBankFollowupModel(Base):
    """题库主问题下的二级追问。"""

    __tablename__ = "question_bank_followups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # 自增主键
    user_id: Mapped[str] = mapped_column(String, nullable=False)                  # 所属用户 ID
    parent_question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("question_bank_items.id", ondelete="CASCADE"), nullable=False
    )  # 所属主问题；随主问题删除级联删除
    question_text: Mapped[str] = mapped_column(Text, nullable=False)              # 追问正文
    reference_answer: Mapped[str | None] = mapped_column(Text, nullable=True)     # 参考答案
    trigger_condition: Mapped[str | None] = mapped_column(Text, nullable=True)    # 触发追问的条件
    source_session_id: Mapped[str | None] = mapped_column(String, nullable=True)  # 来源会话 ID
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)        # 创建时间
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)        # 最后更新时间

    __table_args__ = (
        # 按主问题+时间查询追问
        Index("idx_question_followups_parent", "parent_question_id", "created_at"),
        # 按用户+时间查询追问
        Index("idx_question_followups_user", "user_id", "created_at"),
    )


class InterviewQuestionAttemptModel(Base):
    """一次模拟面试中的真实问答记录。"""

    __tablename__ = "interview_question_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # 自增主键
    user_id: Mapped[str] = mapped_column(String, nullable=False)                  # 所属用户 ID
    session_id: Mapped[str] = mapped_column(String, nullable=False)               # 面试会话 ID
    turn_key: Mapped[str] = mapped_column(String, nullable=False)                 # 轮次键（会话内唯一）
    question_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("question_bank_items.id", ondelete="SET NULL"), nullable=True
    )  # 关联题库主问题；删除后置空
    followup_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("question_bank_followups.id", ondelete="SET NULL"), nullable=True
    )  # 关联题库追问；删除后置空
    asked_question: Mapped[str] = mapped_column(Text, nullable=False)             # 实际提问文本
    user_answer: Mapped[str] = mapped_column(Text, nullable=False)                # 候选人回答文本
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)                # 会话内问答顺序
    evaluation: Mapped[dict] = mapped_column(JSONB, default=dict)                 # 评估结果（JSON）
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)        # 创建时间

    __table_args__ = (
        # 同一用户、会话、轮次只保留一条问答记录
        UniqueConstraint("user_id", "session_id", "turn_key", name="uq_interview_attempt_turn"),
        # 按会话+顺序回放问答
        Index("idx_interview_attempts_session", "user_id", "session_id", "sequence"),
        # 按题目+时间查询使用情况
        Index("idx_interview_attempts_question", "question_id", "created_at"),
    )
