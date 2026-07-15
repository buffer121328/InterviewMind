"""从用户上传的题目文档中确定性提取题目与参考答案。"""

import re
from typing import Any

from app.services.interview_experience.contracts import ExperienceDocument
from app.services.interview_experience.extractor import extract_questions

_QUESTION_PREFIX = re.compile(
    r"^(?:#{1,6}\s*)?(?:(?:q(?:uestion)?|问题|题目|问)\s*\d+\s*[.、:：]?\s*|(?:q(?:uestion)?|问题|题目|问)\s*[:：]\s*)",
    re.I,
)
_ANSWER_PREFIX = re.compile(r"^(?:#{1,6}\s*)?(?:a(?:nswer)?|答案|参考答案|答)\s*[:：]\s*", re.I)
_LIST_PREFIX = re.compile(r"^\s*(?:[-*•]|\d+[.)、])\s*")
_QUESTION_HINTS = ("如何", "为什么", "什么", "怎么", "是否", "介绍", "讲讲", "说说", "区别", "原理")


def _clean(line: str) -> str:
    return re.sub(r"\s+", " ", _LIST_PREFIX.sub("", line)).strip()


def _question_text(line: str, *, allow_hint: bool = True) -> str | None:
    cleaned = _clean(line)
    explicit = bool(_QUESTION_PREFIX.match(cleaned))
    cleaned = _QUESTION_PREFIX.sub("", cleaned).strip(" #")
    if not 5 <= len(cleaned) <= 500:
        return None
    if explicit or cleaned.endswith(("?", "？")) or (
        allow_hint and any(hint in cleaned.lower() for hint in _QUESTION_HINTS)
    ):
        return cleaned
    return None


def parse_question_document(*, content: str, filename: str, source_id: str) -> list[dict[str, Any]]:
    """解析常见 Markdown/Q&A 文档；无法识别答案时仍保留题目。"""
    questions: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    answer_lines: list[str] = []
    answer_started = False

    def flush() -> None:
        nonlocal current, answer_lines, answer_started
        if current is None:
            return
        answer = "\n".join(line for line in answer_lines if line).strip()
        current["reference_answer"] = answer[:10_000] or None
        questions.append(current)
        current = None
        answer_lines = []
        answer_started = False

    for raw_line in content.splitlines():
        line = raw_line.strip()
        cleaned = _clean(line) if line else ""
        is_answer_start = bool(_ANSWER_PREFIX.match(cleaned))
        candidate = _question_text(line, allow_hint=not answer_started) if line and not is_answer_start else None
        if candidate:
            flush()
            current = {
                "question_text": candidate,
                "reference_answer": None,
                "tags": ["来源:文件上传", filename[:100]],
                "difficulty": "medium",
                "target_skill": None,
                "question_type": "tech",
                "source_type": "upload",
                "source_id": source_id,
            }
            continue
        if current is not None:
            if is_answer_start:
                answer_started = True
            answer_lines.append(_ANSWER_PREFIX.sub("", cleaned))
    flush()

    if not questions:
        document = ExperienceDocument(
            source="upload",
            source_id=source_id,
            title=filename,
            content=content,
        )
        questions = extract_questions([document])
        for question in questions:
            question["source_type"] = "upload"
            question["tags"] = ["来源:文件上传", filename[:100]]

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for question in questions:
        key = re.sub(r"\W+", "", str(question["question_text"])).lower()
        if key and key not in seen:
            seen.add(key)
            deduped.append(question)
    return deduped[:200]
