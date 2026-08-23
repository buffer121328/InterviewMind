"""提供简历生成复核相关后端功能。"""

from __future__ import annotations

import json
import logging
from typing import Any, Mapping

from ai.llm.llm_utils import clean_markdown_response, invoke_structured
from ai.prompts.resume import build_fact_check_prompt, build_finalize_review_prompt
from app.schemas.llm_outputs import FactCheckOutput, FinalReviewOutput

from ..resume_context import build_resume_fact_sheet
from .support import (
    bounded_generation_sources,
    current_generation_deadline,
    get_keyword_analysis,
)

logger = logging.getLogger(__name__)


def _verification_failure(error_type: str) -> dict[str, Any]:
    """处理失败相关后端逻辑。"""
    return {
        "is_excessive": True,
        "risk_details": [{
            "type": "verifier_unavailable",
            "location": "整份简历",
            "original": "待独立核查",
            "fabricated": "无法确认",
            "reason": f"独立事实核查失败：{error_type}",
        }],
        "verification_error": error_type,
    }


async def node_fact_check(state: Mapping[str, Any]) -> dict[str, Any]:
    """处理节点事实检查相关后端逻辑。"""
    resume_content = str(state.get("resume_content") or "")
    draft_content = str(state.get("optimized_draft") or state.get("draft_content") or "")
    user_answers = state.get("user_answers") or {}
    api_config = state.get("api_config")
    fact_sheet = build_resume_fact_sheet(resume_content)
    stage_context = bounded_generation_sources(
        stage="fact_check",
        sources=[
            ("resume_facts", fact_sheet.model_dump(), 6000, "head_tail"),
            ("draft", draft_content, 9000, "sections"),
            ("user_answers", user_answers, 1000, "authoritative"),
        ],
    )
    try:
        result = await invoke_structured(
            build_fact_check_prompt(
                resume_content=stage_context.values["resume_facts"],
                draft_content=stage_context.values["draft"],
                user_inputs=stage_context.values["user_answers"] or "无",
            ),
            FactCheckOutput,
            api_config,
            channel="reflector",
            temperature=0.0,
            max_retries=1,
            deadline=current_generation_deadline(),
            call_metadata={
                **stage_context.call_metadata,
                "validator_role": "independent_fact_verifier",
                "verification_phase": "optimized_draft",
            },
        )
        payload = result.model_dump()
        payload["evidence_checks"] = await _run_evidence_checks(
            payload.get("risk_details") or [],
            source_text=resume_content,
            user_id=str(state.get("user_id") or "default_user"),
            api_config=api_config,
        )
        logger.info("独立事实核查完成: is_excessive=%s", payload.get("is_excessive"))
        return {"fact_check_result": payload}
    except Exception as exc:
        logger.error("独立事实核查失败: %s", type(exc).__name__)
        return {"fact_check_result": _verification_failure(type(exc).__name__)}


async def _run_evidence_checks(
    risk_details: list[Any],
    *,
    source_text: str,
    user_id: str,
    api_config: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Run bounded deterministic claim checks through the verification tool."""
    from ai.runtime.context import AgentContext
    from ai.tools.governed_runtime import GovernedToolRuntime

    if not risk_details or not source_text:
        return []
    context = AgentContext(
        user_id=user_id,
        api_config={"resume_content": source_text, **dict(api_config or {})},
        permissions=frozenset({"evidence.verify"}),
    )
    runtime = GovernedToolRuntime(context, groups=("verification",))
    checks: list[dict[str, Any]] = []
    for detail in risk_details[:8]:
        if not isinstance(detail, Mapping):
            continue
        claim = str(detail.get("fabricated") or detail.get("optimized_text") or "").strip()
        if not claim:
            continue
        try:
            result = await runtime.execute(
                "verify_claim_against_source",
                {"claim": claim},
                group="verification",
                workflow_name="resume_generation",
                stage="fact_check",
            )
        except Exception as exc:
            result = {"error": type(exc).__name__}
        checks.append({"claim": claim[:300], "result": result})
    return checks


def _warning_text(fact_check_result: Mapping[str, Any]) -> str:
    """处理文本相关后端逻辑。"""
    if not fact_check_result.get("is_excessive"):
        return ""
    instructions = []
    for index, detail in enumerate(list(fact_check_result.get("risk_details") or [])[:8], 1):
        instructions.append(
            f"  {index}. 【{str(detail.get('location') or '未知位置')[:160]}】\n"
            f"     - 可信来源：{str(detail.get('original') or '无相关描述')[:300]}\n"
            f"     - 风险内容：{str(detail.get('fabricated') or '未知内容')[:300]}\n"
            f"     - 判定理由：{str(detail.get('reason') or '未说明')[:300]}"
        )
    return f"""
**独立验证者警告：必须修正以下事实风险**：

{chr(10).join(instructions)}

**修正规则**：删除无依据事实，或还原为可信来源中的克制表述；不得用“熟悉/了解”掩盖不存在的经历或技能。
"""


async def node_finalize_and_review(state: Mapping[str, Any]) -> dict[str, Any]:
    """处理节点收尾复核相关后端逻辑。"""
    draft_content = str(state.get("optimized_draft") or state.get("draft_content") or "")
    fact_check_result = state.get("fact_check_result") or {}
    optimization_result = state.get("optimization_result") or {}
    jd_keywords = get_keyword_analysis(optimization_result).get("jd_keywords", [])[:10]
    stage_context = bounded_generation_sources(
        stage="final_review",
        sources=[
            ("draft", draft_content, 12_000, "sections"),
            ("fact_risks", fact_check_result.get("risk_details", []), 2600, "head_tail"),
        ],
    )
    try:
        result = await invoke_structured(
            build_finalize_review_prompt(
                draft_content=stage_context.values["draft"],
                jd_keywords_json=json.dumps(jd_keywords, ensure_ascii=False),
                warning_text=_warning_text(fact_check_result),
            ),
            FinalReviewOutput,
            state.get("api_config"),
            channel="hr_reviewer",
            temperature=0.2,
            max_retries=1,
            deadline=current_generation_deadline(),
            call_metadata=stage_context.call_metadata,
        )
        return {
            "final_markdown": clean_markdown_response(result.final_content),
            "review_result": {
                "passed": result.review_passed,
                "editor_passed": result.review_passed,
                "issues": fact_check_result.get("risk_details", []),
            },
            "title": result.title,
        }
    except Exception as exc:
        logger.error("润色审查节点失败: %s", type(exc).__name__)
        return {
            "final_markdown": draft_content,
            "review_result": {
                "passed": False,
                "editor_passed": False,
                "issues": fact_check_result.get("risk_details", []),
                "error": type(exc).__name__,
            },
            "title": "新简历",
        }


async def node_verify_final(state: Mapping[str, Any]) -> dict[str, Any]:
    """处理节点最终相关后端逻辑。"""
    resume_content = str(state.get("resume_content") or "")
    final_markdown = str(state.get("final_markdown") or "")
    user_answers = state.get("user_answers") or {}
    fact_sheet = build_resume_fact_sheet(resume_content)
    stage_context = bounded_generation_sources(
        stage="final_fact_verification",
        sources=[
            ("resume_facts", fact_sheet.model_dump(), 6000, "head_tail"),
            ("final_resume", final_markdown, 9000, "sections"),
            ("user_answers", user_answers, 1000, "authoritative"),
        ],
    )
    try:
        result = await invoke_structured(
            build_fact_check_prompt(
                resume_content=stage_context.values["resume_facts"],
                draft_content=stage_context.values["final_resume"],
                user_inputs=stage_context.values["user_answers"] or "无",
            ),
            FactCheckOutput,
            state.get("api_config"),
            channel="reflector",
            temperature=0.0,
            max_retries=1,
            deadline=current_generation_deadline(),
            call_metadata={
                **stage_context.call_metadata,
                "validator_role": "independent_fact_verifier",
                "verification_phase": "final_resume",
            },
        )
        verification = result.model_dump()
        verification["evidence_checks"] = await _run_evidence_checks(
            verification.get("risk_details") or [],
            source_text=resume_content,
            user_id=str(state.get("user_id") or "default_user"),
            api_config=state.get("api_config"),
        )
    except Exception as exc:
        logger.error("最终事实复核失败: %s", type(exc).__name__)
        verification = _verification_failure(type(exc).__name__)

    editor_result = dict(state.get("review_result") or {})
    passed = bool(editor_result.get("editor_passed", editor_result.get("passed", False))) and not bool(
        verification.get("is_excessive")
    )
    return {
        "fact_check_result": verification,
        "review_result": {
            **editor_result,
            "passed": passed,
            "issues": verification.get("risk_details", []),
            "verification_phase": "final_resume",
        },
    }
