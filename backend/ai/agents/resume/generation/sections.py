"""提供简历相关后端功能。"""

from __future__ import annotations

import re
from hashlib import sha256
from typing import Any, Mapping

_SECTION_ALIASES = {
    "summary": ("个人总结", "职业概述", "自我评价", "summary", "profile"),
    "skills": ("专业技能", "技能", "核心技能", "skills"),
    "experience": ("工作经历", "实习经历", "experience"),
    "projects": ("项目经历", "项目经验", "projects"),
    "education": ("教育经历", "教育背景", "education"),
}


def source_fingerprint(*, resume_content: str, job_description: str) -> str:
    """处理来源指纹相关后端逻辑。"""
    payload = f"resume\0{resume_content}\0jd\0{job_description}".encode("utf-8")
    return sha256(payload).hexdigest()


def _section_id(title: str, index: int) -> str:
    """处理ID相关后端逻辑。"""
    normalized = re.sub(r"\s+", "", title).lower()
    for section_id, aliases in _SECTION_ALIASES.items():
        if any(alias.lower() in normalized for alias in aliases):
            return section_id
    return f"other_{index}"


def parse_resume_sections(markdown: str) -> dict[str, str]:
    """解析简历相关后端逻辑。"""
    matches = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", markdown or ""))
    if not matches:
        return {"document": (markdown or "").strip()} if (markdown or "").strip() else {}
    sections: dict[str, str] = {}
    prefix = (markdown[:matches[0].start()] or "").strip()
    if prefix:
        sections["header"] = prefix
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        section_id = _section_id(match.group(1), index)
        sections[section_id] = markdown[match.start():end].strip()
    return sections


def render_resume_sections(sections: Mapping[str, str]) -> str:
    """渲染简历相关后端逻辑。"""
    return "\n\n".join(value.strip() for value in sections.values() if str(value).strip())


def build_section_checkpoint(*, markdown: str, resume_content: str, job_description: str) -> dict[str, Any]:
    """构建检查点相关后端逻辑。"""
    sections = parse_resume_sections(markdown)
    return {
        "version": "resume-sections.v1",
        "source_fingerprint": source_fingerprint(
            resume_content=resume_content,
            job_description=job_description,
        ),
        "sections": sections,
        "completed_sections": list(sections),
    }


def reusable_sections(
    checkpoint: Mapping[str, Any] | None,
    *,
    resume_content: str,
    job_description: str,
) -> dict[str, str]:
    """处理简历相关后端逻辑。"""
    if not checkpoint:
        return {}
    expected = source_fingerprint(resume_content=resume_content, job_description=job_description)
    if checkpoint.get("source_fingerprint") != expected:
        return {}
    raw = checkpoint.get("sections")
    if not isinstance(raw, Mapping):
        return {}
    return {str(key): str(value) for key, value in raw.items() if str(value).strip()}


def select_retry_sections(
    issues: list[Mapping[str, Any]],
    *,
    available_sections: Mapping[str, str],
) -> tuple[str, ...]:
    """选择重试相关后端逻辑。"""
    selected: list[str] = []
    for issue in issues:
        location = str(issue.get("location") or "").lower()
        for section_id, aliases in _SECTION_ALIASES.items():
            if section_id not in available_sections:
                continue
            if section_id in location or any(alias.lower() in location for alias in aliases):
                if section_id not in selected:
                    selected.append(section_id)
    return tuple(selected)


def merge_section_patch(sections: Mapping[str, str], patch: Mapping[str, str]) -> dict[str, str]:
    """处理简历相关后端逻辑。"""
    merged = dict(sections)
    for section_id, content in patch.items():
        if section_id in merged and str(content).strip():
            merged[section_id] = str(content).strip()
    return merged
