"""将题库/面经候选题转换并合入面试计划。"""

from typing import Any, Iterable


def normalize_candidate(candidate: dict[str, Any]) -> dict[str, Any] | None:
    content = str(candidate.get("question_text") or candidate.get("content") or "").strip()
    if not content:
        return None
    item = {
        "topic": str(candidate.get("target_skill") or candidate.get("topic") or "题库题"),
        "content": content,
        "type": str(candidate.get("question_type") or candidate.get("type") or "tech"),
        "hint": str(candidate.get("reference_answer") or candidate.get("hint") or ""),
        "source_type": str(candidate.get("source_type") or "question_bank"),
        "source_id": candidate.get("source_id"),
        "tags": candidate.get("tags") if isinstance(candidate.get("tags"), list) else [],
        "difficulty": str(candidate.get("difficulty") or "medium"),
        "followups": candidate.get("followups") if isinstance(candidate.get("followups"), list) else [],
    }
    if candidate.get("id") is not None:
        item["question_bank_item_id"] = candidate["id"]
    return item


def prepare_candidates(
    experience_questions: Iterable[dict[str, Any]],
    question_bank_items: Iterable[dict[str, Any]],
    max_questions: int,
) -> list[dict[str, Any]]:
    """面经显式选择优先，并按题目文本去重。"""
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in [*experience_questions, *question_bank_items]:
        item = normalize_candidate(raw)
        if item is None:
            continue
        key = " ".join(item["content"].lower().split())
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= max_questions:
            break
    return result


def merge_question_plan(
    candidates: list[dict[str, Any]],
    generated: list[dict[str, Any]],
    max_questions: int,
) -> list[dict[str, Any]]:
    """候选题优先，生成题补足；最终统一连续编号。"""
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in [*candidates, *generated]:
        content = str(item.get("content") or "").strip()
        key = " ".join(content.lower().split())
        if not content or key in seen:
            continue
        seen.add(key)
        merged.append(dict(item))
        if len(merged) >= max_questions:
            break
    for index, item in enumerate(merged, start=1):
        item["id"] = index
    return merged
