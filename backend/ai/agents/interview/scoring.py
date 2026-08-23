"""面试单回答评分能力，复用受治理的面试评分 Prompt 与模型网关。"""

from __future__ import annotations

from typing import Any


async def score_interview_answer(
    payload: dict[str, Any],
    *,
    api_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """评分一个已提交的回答，不驱动面试状态机或执行工具。

    评分仍使用正式面试回答评估 Prompt、结构化输出 Schema 和统一模型网关；
    本入口只返回评估结论，避免把评分冒烟错误路由为推进或结束面试回合。
    """

    from ai.agents.interview.interview_runtime import InterviewRuntime
    from ai.llm.llm_utils import invoke_structured, invoke_structured_with_messages
    from app.config import get_settings
    from app.schemas.interview.interview import EvaluatingOutput

    resolved_api_config = dict(api_config or payload.get("api_config") or {})

    async def llm_invoker(
        prompt: Any,
        output_model: type[EvaluatingOutput],
        *,
        deadline: Any = None,
        call_metadata: dict[str, Any] | None = None,
    ) -> EvaluatingOutput:
        """经统一模型网关调用，保留运行时观测与请求级模型配置。"""

        kwargs = {
            "output_model": output_model,
            "api_config": resolved_api_config,
            "channel": "fast",
            "max_retries": 0,
            "max_tokens": get_settings().interactive_interview_max_output_tokens,
            "deadline": deadline,
        }
        if isinstance(prompt, list):
            return await invoke_structured_with_messages(
                messages=prompt,
                call_metadata=call_metadata,
                **kwargs,
            )
        return await invoke_structured(
            prompt=prompt,
            call_metadata=call_metadata,
            **kwargs,
        )

    runtime = InterviewRuntime(
        state=dict(payload),
        llm_invoker=llm_invoker,
        tool_executor=None,
        api_config=resolved_api_config,
    )
    prompt, call_metadata = runtime._build_evaluating_prompt_bundle(
        runtime._get_last_user_message(),
        runtime._get_current_question(),
        runtime._get_next_question(),
        tool_context="",
        allow_tool_request=False,
    )
    result = await runtime._invoke_evaluating_model(prompt, call_metadata)
    return result.model_dump(mode="json")
