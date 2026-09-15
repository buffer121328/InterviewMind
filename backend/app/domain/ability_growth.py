"""提供能力相关后端功能。"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

ABILITY_PROFILE_REQUIRED_ROUNDS = 3

DIMENSION_KEYS = (
    "professional_competence",
    "execution_results",
    "logic_problem_solving",
    "communication",
    "growth_potential",
    "collaboration",
)


def _record(value: object) -> dict[str, Any]:
    """记录能力相关后端逻辑。"""
    return dict(value) if isinstance(value, Mapping) else {}


def _score(profile: Mapping[str, Any], key: str) -> float | None:
    """处理分数相关后端逻辑。"""
    value = _record(profile.get(key)).get("score")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def build_ability_profile_progress(
    rows: Sequence[Mapping[str, Any]],
    *,
    required_rounds: int = ABILITY_PROFILE_REQUIRED_ROUNDS,
) -> dict[str, Any]:
    """按公司系列有效画像计算生成资格，同时保留全部已完成面试数量。"""
    safe_required = max(1, int(required_rounds))
    completed_rows = [row for row in rows if str(row.get("status") or "") == "completed"]
    company_profile_count = sum(
        1 for row in completed_rows if _record(row.get("company_profile")).get("profile")
    )

    series: dict[str, dict[int, Mapping[str, Any]]] = {}
    for row in completed_rows:
        series_id = str(row.get("series_id") or "").strip()
        round_index = row.get("round_index")
        if not series_id or not isinstance(round_index, int) or round_index < 1 or round_index > safe_required:
            continue
        series.setdefault(series_id, {}).setdefault(round_index, row)

    def series_rank(item: tuple[str, dict[int, Mapping[str, Any]]]) -> tuple[int, int, int, str]:
        _series_id, rounds = item
        eligible = sum(
            1
            for row in rounds.values()
            if _record(row.get("candidate_profile"))
            and _record(row.get("candidate_profile")).get("generation_mode") != "degraded_evidence_only"
        )
        profiled = sum(1 for row in rounds.values() if _record(row.get("candidate_profile")))
        latest = max((str(row.get("updated_at") or "") for row in rounds.values()), default="")
        has_company_profile = int(any(_record(row.get("company_profile")).get("profile") for row in rounds.values()))
        return has_company_profile, eligible, profiled, latest

    selected_rounds = max(series.items(), key=series_rank)[1] if series else {}
    eligible_round_indexes = sorted(
        index
        for index, row in selected_rounds.items()
        if _record(row.get("candidate_profile"))
        and _record(row.get("candidate_profile")).get("generation_mode") != "degraded_evidence_only"
    )
    degraded_round_indexes = sorted(
        index
        for index, row in selected_rounds.items()
        if _record(row.get("candidate_profile")).get("generation_mode") == "degraded_evidence_only"
    )
    profiled_round_count = sum(
        1 for row in selected_rounds.values() if _record(row.get("candidate_profile"))
    )
    ready = company_profile_count > 0
    eligible_rounds = safe_required if ready else len(eligible_round_indexes)

    if ready:
        blocker = "none"
    elif degraded_round_indexes:
        blocker = "degraded_round_reports"
    elif len(selected_rounds) < safe_required or profiled_round_count < safe_required:
        blocker = "incomplete_series"
    else:
        blocker = "company_profile_pending"

    return {
        "completed_rounds": len(completed_rows),
        "eligible_rounds": eligible_rounds,
        "required_rounds": safe_required,
        "remaining_rounds": max(0, safe_required - eligible_rounds),
        "company_profile_count": company_profile_count,
        "degraded_round_indexes": degraded_round_indexes,
        "ready_to_generate": ready,
        "blocker": blocker,
    }


def ability_profile_not_ready_message(progress: Mapping[str, Any]) -> str:
    """把画像准备度转换为可操作且不误报“无面试”的用户提示。"""
    blocker = str(progress.get("blocker") or "incomplete_series")
    completed_rounds = max(0, int(progress.get("completed_rounds") or 0))
    if blocker == "degraded_round_reports":
        indexes = [str(item) for item in progress.get("degraded_round_indexes") or []]
        round_text = "、".join(indexes) or "部分"
        return (
            f"已完成 {completed_rounds} 轮面试，但当前三轮系列第 {round_text} 轮报告为未评分降级结果。"
            "请在历史面试中重新生成这些轮次的深度报告，并最后重新生成第 3 轮报告。"
        )
    if blocker == "company_profile_pending":
        return "三轮有效画像已经齐全，但公司总画像尚未生成。请重新生成第 3 轮深度报告。"
    return (
        f"已完成 {completed_rounds} 轮面试，但尚无可用的公司三轮总画像。"
        "请通过“继续下一轮”完成同一公司的三轮系列。"
    )


def build_ability_growth_record(
    *,
    overall: Mapping[str, Any],
    source_rows: Sequence[Mapping[str, Any]],
    progress: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """构建能力记录相关后端逻辑。"""
    sources: list[dict[str, Any]] = []
    for row in source_rows:
        payload = _record(row.get("company_profile"))
        profile = _record(payload.get("profile"))
        if not profile:
            continue
        sources.append(
            {
                "session_id": str(row.get("session_id") or ""),
                "series_id": str(row.get("series_id") or "") or None,
                "title": str(row.get("title") or row.get("company_info") or row.get("series_id") or "历史面试"),
                "completed_at": str(row.get("updated_at") or ""),
                "profile": profile,
            }
        )

    changes: dict[str, float] = {}
    if len(sources) >= 2:
        latest = sources[0]["profile"]
        previous = sources[1]["profile"]
        for key in DIMENSION_KEYS:
            latest_score = _score(latest, key)
            previous_score = _score(previous, key)
            if latest_score is not None and previous_score is not None:
                changes[key] = round(latest_score - previous_score, 2)

    return {
        "success": True,
        "profile": _record(overall.get("profile")),
        "generated_at": overall.get("updated_at"),
        "sample_count": len(sources),
        "sources": sources,
        "dimension_changes": changes,
        "progress": dict(progress or build_ability_profile_progress([])),
    }
