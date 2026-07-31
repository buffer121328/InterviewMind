"""面试 RAG 的数据结构。"""

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class RagEvidence:
    """统一证据条目。"""

    source_type: str
    source_id: str
    source_title: str = ""
    evidence: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    retrieval_mode: str = "structured"
    retrieval_score: float = 0.0
    namespace: str = "user_private"
    trust_level: str = "user_private"

    def to_dict(self) -> dict[str, Any]:
        """将持久化对象转换为稳定的字典表示，供 API 或审计边界使用；不改变对象状态，也不主动暴露未声明的敏感字段。"""
        return asdict(self)


@dataclass
class RagResult:
    """RAG 检索结果。"""

    retrieval_mode: str = "structured"
    fallback_reason: Optional[str] = None
    evidences: list[RagEvidence] = field(default_factory=list)
    query_used: str = ""
    total_candidates: int = 0
    retrieval_trace: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """将持久化对象转换为稳定的字典表示，供 API 或审计边界使用；不改变对象状态，也不主动暴露未声明的敏感字段。"""
        return {
            "retrieval_mode": self.retrieval_mode,
            "fallback_reason": self.fallback_reason,
            "evidences": [e.to_dict() for e in self.evidences],
            "query_used": self.query_used,
            "total_candidates": self.total_candidates,
            "retrieval_trace": self.retrieval_trace,
        }



@dataclass
class RetrievalQuery:
    """结构化检索 query。"""

    text: str = ""
    source_types: Optional[list[str]] = None
    target_skills: Optional[list[str]] = None
    tags: Optional[list[str]] = None
    is_verified: Optional[bool] = None
