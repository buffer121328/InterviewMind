"""不依赖模型的可信来源声明核验原语。"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any


def _normalize_evidence_text(value: str) -> str:
    """统一大小写和空白，避免格式差异影响确定性核验。"""

    return re.sub(r"\s+", "", str(value or "")).casefold()


def _source_items(source: str | Sequence[str]) -> list[str]:
    """把单段来源或有界来源列表转换为稳定字符串列表。"""

    if isinstance(source, str):
        return [source]
    return [str(item) for item in source]


def verify_claim_against_source(
    claim: str,
    source: str | Sequence[str],
) -> dict[str, Any]:
    """核验声明是否被可信来源直接支持，且不在结果中回传来源原文。

    完整来源包含声明时视为强证据；较长的来源片段被声明包含时视为弱证据，
    但短技术词不能为年限、规模或职责扩张背书。返回值只包含来源索引，避免
    把完整简历或候选人亮点写入工具审计结果。
    """

    normalized_claim = _normalize_evidence_text(claim)
    matches: list[int] = []
    match_type = "none"
    confidence = 0.0

    if normalized_claim:
        for index, raw_source in enumerate(_source_items(source)):
            normalized_source = _normalize_evidence_text(raw_source)
            if not normalized_source:
                continue
            if normalized_claim in normalized_source:
                matches.append(index)
                match_type = "claim_in_source"
                confidence = 1.0
                continue
            if (
                normalized_source in normalized_claim
                and len(normalized_source) >= 6
                and len(normalized_source) / len(normalized_claim) >= 0.5
            ):
                matches.append(index)
                if match_type == "none":
                    match_type = "source_fragment_in_claim"
                    confidence = 0.7

    has_evidence = bool(matches)
    return {
        "claim": claim,
        "has_evidence": has_evidence,
        "confidence": confidence if has_evidence else 0.0,
        "match_type": match_type if has_evidence else "none",
        "matched_source_indexes": matches[:10],
        "note": (
            "声明可在可信来源中找到依据"
            if has_evidence
            else "声明未在可信来源中找到直接依据，需要用户确认"
        ),
    }


def claim_has_evidence(claim: str, source: str | Sequence[str]) -> bool:
    """返回声明是否被来源支持，供固定流程中的本地校验复用。"""

    return bool(verify_claim_against_source(claim, source)["has_evidence"])
