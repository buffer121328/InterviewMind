"""内置托管提示词目录：从注册表导出可管理的提示词元数据。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from ai.prompts.registry import PromptManagementTag, prompt_management_tags, prompt_registry

# 匹配 LangChain 单花括号变量，转换为 Mustache 双花括号。
_LANGCHAIN_VARIABLE = re.compile(r"(?<!{){([A-Za-z_][A-Za-z0-9_]*)}(?!})")
# 消息模板类型到角色名的映射。
_CHAT_ROLE_BY_TEMPLATE = {
    "SystemMessagePromptTemplate": "system",
    "HumanMessagePromptTemplate": "user",
    "AIMessagePromptTemplate": "assistant",
}
# 历史已下线但仍存在的远端内置提示词展示信息。
# 旧版远端管理记录仍可能存在，但不再允许通过管理 API 复活。
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
    """一个可同步到 Langfuse 的内置提示词。"""

    # 提示词名称。
    # 名称。
    name: str
    # 提示词版本。
    # 版本字符串。
    version: str
    # 提示词类型（文本或聊天）。
    # prompt_type（Literal 类型）。
    prompt_type: Literal["text", "chat"]
    # 渲染后的提示词内容（文本或消息列表）。
    # 提示词文本。
    prompt: str | list[dict[str, str]]
    # 提示词用途说明。
    # 描述文本。
    description: str


@dataclass(frozen=True, slots=True)
class PromptPresentation:
    """提示词在管理列表中的展示信息。"""

    # 展示名称。
    # display 的名称。
    display_name: str
    # 功能分组。
    # functional_group（str 类型）。
    functional_group: str
    # 是否内置提示词。
    # 是否builtin。
    is_builtin: bool
    # 后端功能标签，由 Prompt 注册表定义。
    # management 标签。
    management_tags: tuple[PromptManagementTag, ...]


def _builtin_functional_group(name: str) -> str:
    """按提示词名称前缀归类功能分组。

    Args:
        name: 提示词名称。
    """
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
    """返回提示词的展示信息；未知名称按历史记录或自定义处理。

    Args:
        name: 提示词名称。
    """
    versions = prompt_registry.versions(name)
    if not versions:
        historical = _KNOWN_HISTORICAL_PRESENTATIONS.get(name)
        if historical:
            return PromptPresentation(
                display_name=historical[0],
                functional_group=historical[1],
                is_builtin=True,
                management_tags=prompt_management_tags("domain-ability-analysis"),
            )
        return PromptPresentation(
            display_name=name,
            functional_group="自定义提示词",
            is_builtin=False,
            management_tags=prompt_management_tags("domain-custom-prompt"),
        )
    spec = prompt_registry.get(name, versions[-1])
    functional_group = _builtin_functional_group(name)
    return PromptPresentation(
        display_name=spec.description or "未命名内置提示词",
        functional_group=functional_group,
        is_builtin=True,
        management_tags=spec.management_tags,
    )


def _to_mustache(template: str) -> str:
    """把 LangChain 单花括号变量转成 Mustache 双花括号。

    Args:
        template: 原始模板文本。
    """
    return _LANGCHAIN_VARIABLE.sub(r"{{\1}}", template)


def _serialize_prompt(name: str, version: str) -> BuiltinManagedPrompt | None:
    """把注册表提示词序列化为可同步的结构；聊天模板无角色消息时返回 None。

    Args:
        name: 提示词名称。
        version: 提示词版本。
    """
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
    """返回注册表中所有内置提示词的最新版本。"""
    prompts: list[BuiltinManagedPrompt] = []
    for name in prompt_registry.names():
        versions = prompt_registry.versions(name)
        if not versions:
            continue
        serialized = _serialize_prompt(name, versions[-1])
        if serialized is not None:
            prompts.append(serialized)
    return tuple(prompts)
