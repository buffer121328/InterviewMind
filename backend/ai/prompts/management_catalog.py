"""提供管理相关后端功能。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from ai.prompts.registry import prompt_registry

_LANGCHAIN_VARIABLE = re.compile(r"(?<!{){([A-Za-z_][A-Za-z0-9_]*)}(?!})")
_CHAT_ROLE_BY_TEMPLATE = {
    "SystemMessagePromptTemplate": "system",
    "HumanMessagePromptTemplate": "user",
    "AIMessagePromptTemplate": "assistant",
}
_KNOWN_HISTORICAL_PRESENTATIONS = {
    # Langfuse Cloud 中可能仍有迁移前的远端版本；它们虽然不再参与代码注册，
    # 但仍属于本产品维护的历史内置提示词，列表展示应保留“内置”标签。
    "analysis.candidate_profile": ("单场能力画像", "能力分析"),
    "analysis.weakness_report": ("短板报告", "能力分析"),
}


_RETIRED_MANAGED_PROMPT_NAMES = frozenset({
    "jobs.greeting",
    "jobs.greeting_reflection",
})


def is_retired_managed_prompt(name: str) -> bool:
    """判断提示词名称是否属于已退役的内置管理记录。

    Args:
        name: 名称。
    """

    return name in _RETIRED_MANAGED_PROMPT_NAMES


_KNOWN_HISTORICAL_PRESENTATIONS = {
    # Langfuse Cloud 中可能仍有迁移前的远端版本；它们虽然不再参与代码注册，
    # 但仍属于本产品维护的历史内置提示词，列表展示应保留“内置”标签。
    "analysis.candidate_profile": ("单场能力画像", "能力分析"),
    "analysis.weakness_report": ("短板报告", "能力分析"),
}


@dataclass(frozen=True, slots=True)
class BuiltinManagedPrompt:
    """定义内置托管提示词相关后端数据结构或服务组件。"""

    name: str
    version: str
    prompt_type: Literal["text", "chat"]
    prompt: str | list[dict[str, str]]
    description: str


@dataclass(frozen=True, slots=True)
class PromptPresentation:
    """定义提示词展示相关后端数据结构或服务组件。"""

    display_name: str
    functional_group: str
    is_builtin: bool


def _builtin_functional_group(name: str) -> str:
    """处理内置相关后端逻辑。"""
    if name.startswith("interview."):
        return "模拟面试"
    if name.startswith("voice."):
        return "语音面试"
    if name.startswith("analysis."):
        return "能力分析"
    if name.startswith("jobs."):
        return "岗位处理"
    if name.startswith("resume.jd_match."):
        return "岗位匹配"
    if name in {
        "resume.needs_analysis",
        "resume.draft_generation",
        "resume.draft_optimization",
        "resume.fact_check",
        "resume.finalize_review",
    }:
        return "简历生成"
    if name == "resume.analysis":
        return "简历分析"
    if name.startswith("resume.assembler.") or name == "resume.material_extraction":
        return "简历素材"
    if name.startswith("resume."):
        return "简历处理"
    return "其他内置提示词"


def prompt_presentation(name: str) -> PromptPresentation:
    """处理提示词展示相关后端逻辑。"""
    versions = prompt_registry.versions(name)
    if not versions:
        historical = _KNOWN_HISTORICAL_PRESENTATIONS.get(name)
        if historical:
            return PromptPresentation(
                display_name=historical[0],
                functional_group=historical[1],
                is_builtin=True,
            )
        return PromptPresentation(
            display_name=name,
            functional_group="自定义提示词",
            is_builtin=False,
        )
    spec = prompt_registry.get(name, versions[-1])
    return PromptPresentation(
        display_name=spec.description or "未命名内置提示词",
        functional_group=_builtin_functional_group(name),
        is_builtin=True,
    )


def _to_mustache(template: str) -> str:
    """处理管理相关后端逻辑。"""
    return _LANGCHAIN_VARIABLE.sub(r"{{\1}}", template)


def _serialize_prompt(name: str, version: str) -> BuiltinManagedPrompt | None:
    spec = prompt_registry.get(name, version)
    template = spec.template
    raw_template = getattr(template, "template", None)
    if isinstance(raw_template, str):
        return BuiltinManagedPrompt(
            name=name,
            version=version,
            prompt_type="text",
            prompt=_to_mustache(raw_template),
            description=spec.description,
        )

    messages: list[dict[str, str]] = []
    for message in getattr(template, "messages", []):
        content = getattr(getattr(message, "prompt", None), "template", None)
        role = _CHAT_ROLE_BY_TEMPLATE.get(type(message).__name__)
        if isinstance(content, str) and role:
            messages.append({"role": role, "content": _to_mustache(content)})
    if not messages:
        return None
    return BuiltinManagedPrompt(
        name=name,
        version=version,
        prompt_type="chat",
        prompt=messages,
        description=spec.description,
    )


def latest_builtin_managed_prompts() -> tuple[BuiltinManagedPrompt, ...]:
    """处理内置托管提示词相关后端逻辑。"""
    prompts: list[BuiltinManagedPrompt] = []
    for name in prompt_registry.names():
        versions = prompt_registry.versions(name)
        if not versions:
            continue
        serialized = _serialize_prompt(name, versions[-1])
        if serialized is not None:
            prompts.append(serialized)
    return tuple(prompts)
