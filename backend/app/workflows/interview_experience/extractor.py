"""从面经正文中确定性抽取面试题，避免为简单清洗调用 LLM。"""

import re

from app.schemas.experience_provider import ExperienceDocument


QUESTION_HINTS = ("如何", "为什么", "什么", "怎么", "是否", "介绍", "讲讲", "说说", "聊聊", "区别", "原理")
SKILL_KEYWORDS = {
    "Python": ("python", "django", "fastapi"),
    "Java": ("java", "spring", "jvm"),
    "Go": ("golang", "go语言", "goroutine"),
    "数据库": ("mysql", "postgresql", "sql", "索引", "事务"),
    "缓存": ("redis", "缓存"),
    "分布式系统": ("分布式", "消息队列", "kafka", "一致性"),
}


def _normalise_line(line: str) -> str:
    line = re.sub(r"^\s*(?:[-*•]|\d+[.)、]|[一二三四五六七八九十]+[、.])\s*", "", line)
    line = re.sub(r"^(?:面试官|问题|题目|问)\s*[:：]\s*", "", line)
    return re.sub(r"\s+", " ", line).strip(" -—:：")


def _looks_like_question(line: str) -> bool:
    if not 5 <= len(line) <= 500:
        return False
    lowered = line.lower()
    return line.endswith(("?", "？")) or any(hint in lowered for hint in QUESTION_HINTS)


def _target_skill(question: str) -> str | None:
    lowered = question.lower()
    for skill, keywords in SKILL_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return skill
    return None


def _question_type(question: str) -> str:
    if any(word in question for word in ("设计", "架构", "高并发", "系统")):
        return "system_design"
    if any(word in question for word in ("经历", "冲突", "失败", "挑战", "团队")):
        return "behavior"
    return "tech"


def extract_questions(documents: list[ExperienceDocument]) -> list[dict[str, object]]:
    questions: list[dict[str, object]] = []
    seen: set[str] = set()
    for document in documents:
        for raw_line in document.content.splitlines():
            question = _normalise_line(raw_line)
            if not _looks_like_question(question):
                continue
            dedupe_key = re.sub(r"[\s?？。,.，]", "", question).lower()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            skill = _target_skill(question)
            tags = [f"来源:{document.source}"]
            if document.query:
                tags.append(document.query[:40])
            if skill:
                tags.append(skill)
            questions.append(
                {
                    "question_text": question,
                    "reference_answer": None,
                    "tags": tags,
                    "difficulty": "medium",
                    "target_skill": skill,
                    "question_type": _question_type(question),
                    "source_type": f"experience:{document.source}",
                    "source_id": document.source_id,
                }
            )
    return questions
