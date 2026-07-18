"""离线 RAG 检索质量回归评测。

不调用真实数据库、embedding 或 LLM；从 tests/datasets/rag_golden.json 加载
固定 golden corpus，验证 RAG 编排能把 JD/简历/短板上下文映射到正确证据来源，
并在无证据时安全 fallback。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pytest

pytest.importorskip("deepeval")

from deepeval import assert_test
from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase

import app.services.interview.interview_rag as rag_module

_DATASET = json.loads((Path(__file__).resolve().parents[1] / "datasets" / "rag_golden.json").read_text())
CORPUS = _DATASET["corpus"]


@dataclass(frozen=True)
class GoldenCase:
    case_id: str
    job_description: str
    resume: str = ""
    weakness_report: dict | None = None
    target_skills: list[str] | None = None
    expected_source_ids: frozenset[str] = frozenset()
    expected_source_types: frozenset[str] = frozenset()
    min_recall_at_5: float = 0.6

    @classmethod
    def from_dict(cls, raw: dict) -> "GoldenCase":
        return cls(
            case_id=raw["case_id"],
            job_description=raw["job_description"],
            resume=raw.get("resume", ""),
            weakness_report=raw.get("weakness_report"),
            target_skills=raw.get("target_skills"),
            expected_source_ids=frozenset(raw.get("expected_source_ids", [])),
            expected_source_types=frozenset(raw.get("expected_source_types", [])),
            min_recall_at_5=float(raw.get("min_recall_at_5", 0.6)),
        )


GOLDEN_CASES = [GoldenCase.from_dict(item) for item in _DATASET["cases"]]


class OfflineRagQualityRepo:
    """基于 token overlap 的可解释离线召回桩。"""

    async def search_structured(self, **kwargs):
        return []

    async def search_by_vector(self, **kwargs):
        return []

    async def search_by_text(self, **kwargs):
        query_terms = _terms(kwargs["query"])
        allowed = set(kwargs.get("source_types") or [])
        hits = []
        for item in CORPUS:
            if allowed and item["source_type"] not in allowed:
                continue
            overlap = query_terms.intersection(_terms(item["content"]))
            if not overlap:
                continue
            hits.append({
                **item,
                "text_score": min(1.0, 0.35 + 0.15 * len(overlap)),
            })
        return sorted(hits, key=lambda row: row["text_score"], reverse=True)[: kwargs.get("limit", 8)]


def _terms(text: str) -> set[str]:
    normalized = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return {term for term in normalized.split() if len(term) >= 3}


def _recall_at(retrieved_ids: Iterable[str], expected_ids: set[str], k: int) -> float:
    top_k = set(list(retrieved_ids)[:k])
    return len(top_k.intersection(expected_ids)) / len(expected_ids)


class RagRetrievalQualityMetric(BaseMetric):
    """DeepEval 自定义确定性指标：验证 RAG recall@k 与来源覆盖。"""

    def __init__(self, *, threshold: float = 0.8, k: int = 5):
        self.threshold = threshold
        self.k = k
        self.score = None
        self.reason = None
        self.success = None
        self.async_mode = False
        self.include_reason = True

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        metadata = test_case.metadata or {}
        retrieved_ids = list(metadata.get("retrieved_source_ids", []))
        retrieved_types = set(metadata.get("retrieved_source_types", []))
        expected_ids = set(metadata.get("expected_source_ids", []))
        expected_types = set(metadata.get("expected_source_types", []))
        min_recall = float(metadata.get("min_recall_at_k", self.threshold))

        recall = _recall_at(retrieved_ids, expected_ids, self.k) if expected_ids else 1.0
        source_coverage = (
            len(retrieved_types.intersection(expected_types)) / len(expected_types)
            if expected_types
            else 1.0
        )
        self.score = round((recall + source_coverage) / 2, 4)
        self.success = recall >= min_recall and source_coverage >= 1.0
        self.reason = (
            f"recall@{self.k}={recall:.2f}, source_coverage={source_coverage:.2f}, "
            f"retrieved_ids={retrieved_ids}"
        )
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        return self.measure(test_case, *args, **kwargs)

    def is_successful(self) -> bool:
        return bool(self.success)

    @property
    def __name__(self):
        return "RAG Retrieval Quality"


class RagFallbackSafetyMetric(BaseMetric):
    """DeepEval 自定义确定性指标：无证据时必须安全 fallback。"""

    def __init__(self):
        self.threshold = 1.0
        self.score = None
        self.reason = None
        self.success = None
        self.async_mode = False
        self.include_reason = True

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        metadata = test_case.metadata or {}
        mode = metadata.get("retrieval_mode")
        evidence_count = int(metadata.get("evidence_count", -1))
        fallback_reason = str(metadata.get("fallback_reason") or "")
        self.success = mode == "fallback" and evidence_count == 0 and "no_evidence" in fallback_reason
        self.score = 1.0 if self.success else 0.0
        self.reason = f"mode={mode}, evidence_count={evidence_count}, fallback_reason={fallback_reason}"
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        return self.measure(test_case, *args, **kwargs)

    def is_successful(self) -> bool:
        return bool(self.success)

    @property
    def __name__(self):
        return "RAG Fallback Safety"


@pytest.mark.fast
@pytest.mark.eval
@pytest.mark.parametrize("case", GOLDEN_CASES, ids=lambda case: case.case_id)
@pytest.mark.asyncio
async def test_offline_rag_recall_and_source_coverage(monkeypatch, case: GoldenCase):
    from app.repositories.interview import rag_index_repo

    monkeypatch.setattr(rag_index_repo, "get_rag_index_repo", lambda: OfflineRagQualityRepo())
    monkeypatch.setattr(rag_module, "VECTOR_ENABLED", False)
    monkeypatch.setattr(rag_module, "AGENTIC_MODE", "off")

    result = await rag_module.run_rag_pipeline(
        user_id="user-1",
        job_description=case.job_description,
        resume=case.resume,
        weakness_report=case.weakness_report,
        target_skills=case.target_skills,
    )

    retrieved_ids = [item.source_id for item in result.evidences]
    retrieved_source_types = {item.source_type for item in result.evidences}

    assert result.retrieval_mode == "structured"
    assert result.retrieval_trace["source_counts"]

    assert_test(
        LLMTestCase(
            name=case.case_id,
            input=case.job_description,
            actual_output="\n".join(item.evidence for item in result.evidences),
            retrieval_context=[item.evidence for item in result.evidences],
            metadata={
                "retrieval_mode": result.retrieval_mode,
                "retrieved_source_ids": retrieved_ids,
                "retrieved_source_types": sorted(retrieved_source_types),
                "expected_source_ids": sorted(case.expected_source_ids),
                "expected_source_types": sorted(case.expected_source_types),
                "min_recall_at_k": case.min_recall_at_5,
            },
        ),
        [RagRetrievalQualityMetric(k=5)],
    )


@pytest.mark.fast
@pytest.mark.eval
@pytest.mark.asyncio
async def test_offline_rag_quality_falls_back_when_corpus_has_no_match(monkeypatch):
    from app.repositories.interview import rag_index_repo

    fallback_case = _DATASET["fallback_case"]
    monkeypatch.setattr(rag_index_repo, "get_rag_index_repo", lambda: OfflineRagQualityRepo())
    monkeypatch.setattr(rag_module, "VECTOR_ENABLED", False)
    monkeypatch.setattr(rag_module, "AGENTIC_MODE", "off")

    result = await rag_module.run_rag_pipeline(
        user_id="user-1",
        job_description=fallback_case["job_description"],
    )

    assert_test(
        LLMTestCase(
            name=fallback_case["case_id"],
            input=fallback_case["job_description"],
            actual_output=result.fallback_reason or "",
            retrieval_context=[],
            metadata={
                "retrieval_mode": result.retrieval_mode,
                "evidence_count": len(result.evidences),
                "fallback_reason": result.fallback_reason,
            },
        ),
        [RagFallbackSafetyMetric()],
    )
