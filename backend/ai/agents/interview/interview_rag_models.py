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
        """转换 `dict`。"""
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
        """转换 `dict`。"""
        return {
            "retrieval_mode": self.retrieval_mode,
            "fallback_reason": self.fallback_reason,
            "evidences": [e.to_dict() for e in self.evidences],
            "query_used": self.query_used,
            "total_candidates": self.total_candidates,
            "retrieval_trace": self.retrieval_trace,
        }

    def to_legacy_context(self) -> dict[str, Any]:
        """转换为 retrieval_repo 旧格式，兼容 interview_planner 现有调用。"""
        bank_questions = []
        candidate_materials = []
        weakness_categories = []
        historical_questions = []
        jd_keywords = []

        for ev in self.evidences:
            if ev.source_type in {"question_bank", "question_bank_followup"}:
                bank_questions.append({
                    "id": ev.source_id,
                    "question_text": ev.evidence,
                    "target_skill": ev.metadata.get("target_skill"),
                    "difficulty": ev.metadata.get("difficulty", "medium"),
                    "tags": ev.metadata.get("tags", []),
                })
            elif ev.source_type == "candidate_material":
                candidate_materials.append({
                    "id": ev.source_id,
                    "material_type": ev.metadata.get("material_type"),
                    "title": ev.metadata.get("title", ev.source_title),
                    "content": ev.evidence,
                    "tags": ev.metadata.get("tags", []),
                })
            elif ev.source_type == "weakness_report":
                weakness_categories.append({
                    "category": ev.metadata.get("category"),
                    "severity": ev.metadata.get("severity", "medium"),
                    "description": ev.evidence,
                })
            elif ev.source_type == "historical_question":
                historical_questions.append(ev.evidence)
            elif ev.source_type == "jd_analysis":
                keywords = ev.metadata.get("matched_keywords", [])
                keywords.extend(ev.metadata.get("missing_keywords", []))
                jd_keywords.extend(keywords)

        return {
            "jd_keywords": list(dict.fromkeys(jd_keywords)),
            "weakness_categories": weakness_categories,
            "historical_questions": historical_questions,
            "bank_questions": bank_questions,
            "candidate_materials": candidate_materials,
            "retrieval_mode": self.retrieval_mode,
            "fallback_reason": self.fallback_reason,
            "rag_evidences": [e.to_dict() for e in self.evidences],
            "rag_trace": self.retrieval_trace,
        }


@dataclass
class RetrievalQuery:
    """结构化检索 query。"""

    text: str = ""
    source_types: Optional[list[str]] = None
    target_skills: Optional[list[str]] = None
    tags: Optional[list[str]] = None
    is_verified: Optional[bool] = None
