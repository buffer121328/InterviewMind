"""Pure Markdown assembly for persisted interview reports."""

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
    """Narrow untrusted persisted JSON to a dictionary before reading report fields."""
    return value if isinstance(value, dict) else {}


def _items(value: Any) -> list[Any]:
    """Narrow untrusted persisted JSON to a list before rendering bounded collections."""
    return value if isinstance(value, list) else []


def _inline(value: Any, fallback: str = "暂无") -> str:
    """Collapse one persisted scalar to safe Markdown inline text without allowing new blocks."""
    if value is None:
        return fallback
    text = " ".join(str(value).split()).strip()
    if not text:
        return fallback
    for marker in ("\\", "`", "*", "_", "{", "}", "[", "]", "<", ">", "#", "|"):
        text = text.replace(marker, f"\\{marker}")
    return text


def _append_list(lines: list[str], values: Any, fallback: str = "暂无") -> None:
    """Append a Markdown bullet list while preserving an explicit empty-state sentence."""
    rendered = [_inline(value) for value in _items(values)]
    rendered = [value for value in rendered if value != "暂无"]
    if not rendered:
        lines.append(f"- {fallback}")
        return
    lines.extend(f"- {value}" for value in rendered)


def _priority(value: dict[str, Any]) -> int:
    """Return a bounded sortable priority even for legacy malformed report JSON."""
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
    """Build the single Markdown report used by preview, HTML export, and PDF export.

    Args:
        title: Owner-scoped session title.
        mode: Persisted interview mode.
        round_index: Persisted round number.
        max_questions: Persisted planned main-question count.
        profile: Validated candidate-profile JSON stored on the session.
        weakness_report: Persisted weakness record or its ``report_data`` payload.
        generated_at: Stable report update time shown in the exported document.

    Returns:
        A Markdown document containing the ability profile, evidence, weaknesses,
        representative failures, and an ordered improvement plan.
    """
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
        "## 综合评价",
        "",
        _inline(profile_data.get("overall_assessment")),
        "",
        f"**后续建议：** {_inline(profile_data.get('recommendation'))}",
        "",
        "## 能力画像",
        "",
    ]

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
