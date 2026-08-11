"""提供面试相关后端功能。"""

from __future__ import annotations

from typing import Any

_PROFILE_DIMENSIONS = (
    ("professional_competence", "专业能力"),
    ("execution_results", "执行与结果"),
    ("logic_problem_solving", "逻辑与问题解决"),
    ("communication", "沟通表达"),
    ("growth_potential", "成长潜力"),
    ("collaboration", "协作能力"),
)
_SEVERITY_LABELS = {"high": "高", "medium": "中", "low": "低"}


def _record(value: Any) -> dict[str, Any]:
    """记录面试相关后端逻辑。"""
    return value if isinstance(value, dict) else {}


def _items(value: Any) -> list[Any]:
    """处理条目相关后端逻辑。"""
    return value if isinstance(value, list) else []


def _inline(value: Any, fallback: str = "暂无") -> str:
    """处理行内相关后端逻辑。"""
    if value is None:
        return fallback
    text = " ".join(str(value).split()).strip()
    if not text:
        return fallback
    for marker in ("\\", "`", "*", "_", "{", "}", "[", "]", "<", ">", "#", "|"):
        text = text.replace(marker, f"\\{marker}")
    return text


def _append_list(lines: list[str], values: Any, fallback: str = "暂无") -> None:
    """处理列表相关后端逻辑。"""
    rendered = [_inline(value) for value in _items(values)]
    rendered = [value for value in rendered if value != "暂无"]
    if not rendered:
        lines.append(f"- {fallback}")
        return
    lines.extend(f"- {value}" for value in rendered)


def _priority(value: dict[str, Any]) -> int:
    """处理优先级相关后端逻辑。"""
    try:
        return max(1, min(99, int(value.get("priority") or 99)))
    except (TypeError, ValueError):
        return 99


def build_interview_report_markdown(
    *,
    title: str,
    mode: str,
    round_index: int,
    max_questions: int,
    profile: dict[str, Any],
    weakness_report: dict[str, Any],
    generated_at: str | None = None,
) -> str:
    """构建面试报告Markdown相关后端逻辑。"""
    profile_data = _record(profile)
    weakness_container = _record(weakness_report)
    weakness_data = _record(weakness_container.get("report_data") or weakness_container)
    mode_label = "语音面试" if mode == "voice" else "文字面试"
    lines = [
        f"# {_inline(title, '模拟面试')} · 面试报告",
        "",
        (
            f"> {_inline(mode_label)} · 第 {max(1, int(round_index or 1))} 轮"
            f" · 计划 {max(1, int(max_questions or 1))} 题"
            f" · 更新时间：{_inline(generated_at)}"
        ),
        "",
    ]
    if profile_data.get("generation_mode") == "degraded_evidence_only":
        missing = [
            label for key, label in _PROFILE_DIMENSIONS
            if key in _items(profile_data.get("missing_dimensions"))
        ]
        lines.extend([
            "> ⚠️ 本报告为证据受限降级模式：仅保留已持久化问答，未生成能力评分。",
            f"> 未评分维度：{'、'.join(missing) if missing else '全部能力维度'}",
            "",
        ])
    lines.extend([
        "## 综合评价",
        "",
        _inline(profile_data.get("overall_assessment")),
        "",
        f"**后续建议：** {_inline(profile_data.get('recommendation'))}",
        "",
        "## 能力画像",
        "",
    ])

    for key, label in _PROFILE_DIMENSIONS:
        dimension = _record(profile_data.get(key))
        score = dimension.get("score")
        score_text = f"{score}/10" if isinstance(score, (int, float)) else "暂无评分"
        lines.extend(
            [
                f"### {label} · {score_text}",
                "",
                f"- **评价：** {_inline(dimension.get('reason'))}",
                f"- **证据：** {_inline(dimension.get('evidence'))}",
                f"- **改进建议：** {_inline(dimension.get('improvement_tip'))}",
                f"- **更好回答示例：** {_inline(dimension.get('better_answer_example'))}",
                "",
            ]
        )

    lines.extend(["## 关键优势", ""])
    _append_list(lines, profile_data.get("key_strengths"))
    lines.extend(["", "## 重点短板", ""])
    categories = _items(weakness_data.get("weakness_categories"))
    if categories:
        for raw_category in categories:
            category = _record(raw_category)
            severity = _SEVERITY_LABELS.get(str(category.get("severity")), "中")
            lines.extend(
                [
                    f"### {_inline(category.get('category'), '未分类')} · {severity}优先级",
                    "",
                    _inline(category.get("description")),
                    "",
                ]
            )
    else:
        _append_list(lines, profile_data.get("key_weaknesses"))

    lines.extend(["## 典型问答复盘", ""])
    failures = _items(weakness_data.get("question_failures"))
    if failures:
        for index, raw_failure in enumerate(failures, start=1):
            failure = _record(raw_failure)
            lines.extend(
                [
                    f"### {index}. {_inline(failure.get('question'), '未记录题目')}",
                    "",
                    f"- **你的回答：** {_inline(failure.get('user_answer'))}",
                    f"- **核心问题：** {_inline(failure.get('issue'))}",
                    f"- **改进示例：** {_inline(failure.get('better_example'))}",
                    "",
                ]
            )
    else:
        lines.extend(["- 暂无典型失败问答。", ""])

    lines.extend(["## 改进行动", ""])
    actions = sorted(
        (_record(value) for value in _items(weakness_data.get("improvement_actions"))),
        key=_priority,
    )
    if actions:
        for index, action in enumerate(actions, start=1):
            lines.append(
                f"{index}. {_inline(action.get('action'))}"
                f"（预计投入：{_inline(action.get('estimated_effort'))}）"
            )
    else:
        lines.append("1. 暂无明确行动项。")

    lines.extend(["", "## 推荐练习题", ""])
    _append_list(lines, weakness_data.get("recommended_questions"), "暂无推荐练习题。")
    lines.extend(["", "## 建议练习顺序", ""])
    priority_order = [_inline(value) for value in _items(weakness_data.get("priority_order"))]
    lines.append(" → ".join(priority_order) if priority_order else "暂无建议顺序。")
    return "\n".join(lines).strip() + "\n"


_PUBLIC_DIMENSION_FIELDS = (
    "score", "evidence", "reason", "better_answer_example", "improvement_tip",
)
_PUBLIC_WEAKNESS_FIELDS = {
    "question_evidence": (
        "question_id", "topic", "question_summary", "candidate_claims",
        "demonstrated_skills", "missing_evidence", "communication_observations", "score_or_signal",
    ),
    "weakness_categories": ("category", "description", "severity"),
    "question_failures": ("question", "user_answer", "issue", "better_example"),
    "improvement_actions": ("action", "priority", "estimated_effort"),
}

def _project_public_records(values: Any, fields: tuple[str, ...]) -> list[dict[str, Any]]:
    """只保留公开报告声明字段，隔离模型内部上下文。"""
    return [
        {key: item[key] for key in fields if key in item}
        for item in (_record(value) for value in _items(values))
        if item
    ]


def build_structured_interview_report(profile: object, weakness_report: object) -> tuple[dict, dict]:
    """构建结构化面试报告相关后端逻辑。"""
    profile_data = _record(_record(profile).get("profile") or profile)
    weakness_data = _record(_record(weakness_report).get("report_data") or weakness_report)
    dimensions = {
        key: {
            field: dimension[field]
            for field in _PUBLIC_DIMENSION_FIELDS
            if field in dimension
        }
        for key, _label in _PROFILE_DIMENSIONS
        for dimension in [_record(profile_data.get(key))]
        if dimension
    }
    public_profile = {
        "overall_assessment": str(profile_data.get("overall_assessment") or ""),
        "recommendation": str(profile_data.get("recommendation") or ""),
        "dimensions": dimensions,
        "skill_tags": [value for value in _items(profile_data.get("skill_tags")) if isinstance(value, str)],
        "key_strengths": [value for value in _items(profile_data.get("key_strengths")) if isinstance(value, str)],
        "key_weaknesses": [value for value in _items(profile_data.get("key_weaknesses")) if isinstance(value, str)],
        "generation_mode": str(profile_data.get("generation_mode") or "model_reviewed"),
        "missing_dimensions": [
            value for value in _items(profile_data.get("missing_dimensions")) if isinstance(value, str)
        ],
    }
    public_weakness: dict[str, Any] = {
        key: _project_public_records(weakness_data.get(key), fields)
        for key, fields in _PUBLIC_WEAKNESS_FIELDS.items()
    }
    public_weakness["recommended_questions"] = [
        value for value in _items(weakness_data.get("recommended_questions")) if isinstance(value, str)
    ]
    public_weakness["priority_order"] = [
        value for value in _items(weakness_data.get("priority_order")) if isinstance(value, str)
    ]
    public_weakness["generation_mode"] = str(
        weakness_data.get("generation_mode") or "model_reviewed"
    )
    public_weakness["degradation_reason"] = str(
        weakness_data.get("degradation_reason") or ""
    )
    public_weakness["missing_dimensions"] = [
        value for value in _items(weakness_data.get("missing_dimensions")) if isinstance(value, str)
    ]
    return public_profile, public_weakness
