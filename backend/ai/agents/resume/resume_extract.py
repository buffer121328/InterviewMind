"""Deterministic extraction of a candidate's professional-skills section."""

from __future__ import annotations

import re
from dataclasses import dataclass

_SKILL_HEADING = re.compile(
    r"^(?:专业技能|专业能力|技能|核心技能|技术栈|技术能力|skills?|technical skills?)\s*[:：]?\s*$",
    re.IGNORECASE,
)
_SECTION_HEADING = re.compile(
    r"^(?:个人信息|基本信息|教育经历|教育背景|工作经历|实习经历|项目经历|项目经验|自我评价|个人总结|证书|荣誉|语言能力|求职意向|专业技能|专业能力|技能|核心技能|技术栈|技术能力|skills?|technical skills?)\s*[:：]?\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ResumeSkillsExtraction:
    """Result of best-effort skills-section extraction."""

    content: str
    matched: bool


def _normalize_line(line: str) -> str:
    return re.sub(r"^\s*[-*•▪●]\s*", "", line).strip()


def _heading_text(line: str) -> str:
    return re.sub(r"^#+\s*", "", _normalize_line(line))


def extract_professional_skills(resume: str) -> ResumeSkillsExtraction:
    """Extract the first explicit skills section and fail open when absent."""
    raw = str(resume or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = raw.split("\n")
    start = next(
        (
            index
            for index, line in enumerate(lines)
            if _SKILL_HEADING.fullmatch(_heading_text(line))
        ),
        -1,
    )
    if start < 0:
        return ResumeSkillsExtraction(content=raw.strip(), matched=False)

    skill_lines: list[str] = []
    for line in lines[start + 1 :]:
        normalized = _normalize_line(line)
        if normalized and (normalized.startswith("#") or _SECTION_HEADING.fullmatch(_heading_text(normalized))):
            break
        if normalized:
            skill_lines.append(normalized)
    content = "\n".join(skill_lines).strip()
    return ResumeSkillsExtraction(content=content or raw.strip(), matched=bool(content))
