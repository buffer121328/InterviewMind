"""绑定简历上下文的 Agent 工具。"""

from __future__ import annotations

from typing import Any, Literal, Optional

from langchain_core.tools import tool

from ai.runtime.context import AgentContext
from ai.runtime.execution.deadlines import TaskDeadline
from app.schemas.tools import attach_tool_contract


def make_resume_tools(
    resume_content: str = "",
    job_description: str = "",
    *,
    api_config: Optional[dict] = None,
    user_id: str | None = None,
    deadline: TaskDeadline | None = None,
    call_metadata: dict[str, Any] | None = None,
) -> list[Any]:
    """构造统一 JD 匹配工具，并把简历与模型配置绑定在可信上下文。"""

    bound_job_description = job_description

    @tool
    async def match_jd(
        job_description: str = "",
        mode: Literal["fast", "smart"] = "fast",
    ) -> dict[str, Any]:
        """用 fast 规则或 smart 模型分析运行时简历与目标 JD 的匹配度。"""

        target_jd = job_description or bound_job_description
        # Resolve lazily so workflow tests and controlled adapters can replace
        # the canonical matcher without bypassing the tool contract.
        from ai.agents.resume.jd_matcher import match_jd as run_jd_match

        return await run_jd_match(
            resume_content=resume_content,
            job_description=target_jd,
            mode=mode,
            api_config=api_config,
            user_id=user_id,
            deadline=deadline,
            call_metadata=call_metadata,
        )

    return [
        attach_tool_contract(
            match_jd,
            effect="read",
            permissions=("resume.jd.match",),
            result_retention="summary",
        ),
    ]


async def execute_resume_match(
    *,
    resume_content: str,
    job_description: str,
    mode: Literal["fast", "smart"] = "fast",
    api_config: Optional[dict] = None,
    user_id: str | None = None,
    workflow_name: str = "resume",
    stage: str = "jd_analysis",
    deadline: TaskDeadline | None = None,
    call_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute the registered JD matcher with owner-scoped guard enforcement."""
    from ai.tools.governed_runtime import GovernedToolRuntime

    context = AgentContext(
        user_id=user_id or "default_user",
        api_config={
            "resume_content": resume_content,
            "job_description": job_description,
            **dict(api_config or {}),
        },
        runtime_data={"deadline": deadline, "call_metadata": call_metadata},
        permissions=frozenset({"resume.jd.match"}),
    )
    result = await GovernedToolRuntime(context, groups=("resume",)).execute(
        "match_jd",
        {"job_description": job_description, "mode": mode},
        group="resume",
        workflow_name=workflow_name,
        stage=stage,
    )
    return dict(result)
