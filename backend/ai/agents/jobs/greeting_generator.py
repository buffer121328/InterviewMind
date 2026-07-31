"""
打招呼文案生成器

每条文案基于候选人真实简历和岗位匹配结果生成。
3 种风格：professional / technical / result_oriented。

核心约束（文档 Section 6.4 & 10.2）：
- 完整但克制（100–220 个中文字符）
- 真实（不承诺不存在经历）
- 相关（与岗位匹配）
- 不输出"我非常适合"
- 不写空洞套话
"""

import json
import logging
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from ai.runtime.deadlines import TaskDeadline
from ai.runtime.evidence import claim_has_evidence

logger = logging.getLogger(__name__)


# ============================================================================
# LLM Output Schema
# ============================================================================

class GreetingItemOutput(BaseModel):
    """数据对象，承载 `GreetingItemOutput` 的结构化字段和跨模块契约；只表达数据，不在构造或序列化时执行外部调用。"""
    tone: Literal["professional", "technical", "result_oriented"] = Field(description="文案风格")
    message_text: str = Field(min_length=100, max_length=220, description="100–220 字的第一人称打招呼文案")
    highlights_used: List[str] = Field(description="使用的亮点")
    risk_notes: str = Field(default="", description="风险提示（如有不实内容此处注明）")


class GreetingListOutput(BaseModel):
    """约束模型必须返回三种固定风格，避免缺项导致前端方案不完整。"""

    greetings: List[GreetingItemOutput] = Field(
        min_length=3,
        max_length=3,
        description="3 条打招呼文案",
    )


class GreetingReflectionOutput(BaseModel):
    """Self-review result for truthfulness, relevance, and length-contract compliance."""

    approved: bool = Field(default=False)
    truthfulness_pass: bool = Field(default=False)
    relevance_pass: bool = Field(default=False)
    length_pass: bool = Field(default=False)
    issues: List[str] = Field(default_factory=list)


# ============================================================================
# 生成入口
# ============================================================================

async def generate_greetings(
    company_name: str,
    job_title: str,
    jd_summary: str = "",
    candidate_highlights: str | list[str] | None = None,
    api_config: Optional[dict] = None,
    deadline: TaskDeadline | None = None,
    call_metadata: dict[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    """Generate, reflect on, and at most once rewrite three outreach messages.

    The writer and reflector use separate model channels. Both rounds share the caller's
    deadline; failure or a second rejected draft falls back to deterministic evidence-only
    copy rather than returning an unreviewed model draft.
    """
    from ai.llm.llm_utils import invoke_structured
    from ai.prompts.jobs import build_greeting_prompt, build_greeting_reflection_prompt

    if isinstance(candidate_highlights, str):
        raw_highlights = [
            item.strip(" -•\t")
            for item in candidate_highlights.replace("，", "\n").splitlines()
            if item.strip(" -•\t")
        ]
    else:
        raw_highlights = [str(item).strip() for item in candidate_highlights or []]
    highlights = list(dict.fromkeys(item[:220] for item in raw_highlights if item))[:5]
    highlights_text = ""
    if highlights:
        highlights_text = "\n【候选人真实亮点】：\n" + "\n".join(
            f"- {item}" for item in highlights
        )
    jd_text = f"\n【岗位关键信息】：\n{jd_summary[:500]}" if jd_summary else ""

    reflection_text = ""
    try:
        for round_index in range(2):
            prompt = build_greeting_prompt(
                company_name=company_name,
                job_title=job_title,
                jd_summary=jd_summary[:500],
                highlights_text=highlights_text,
                jd_text=jd_text,
                reflection_text=reflection_text,
            )
            result = await invoke_structured(
                prompt,
                GreetingListOutput,
                api_config,
                channel="content_writer",
                temperature=0.5 if round_index == 0 else 0.3,
                deadline=deadline,
                call_metadata={
                    **dict(call_metadata or {}),
                    "stage": f"greeting.draft.{round_index + 1}",
                    "reflection_round": round_index + 1,
                },
            )
            greetings, deterministic_issues = _validate_generated_greetings(
                result.model_dump().get("greetings", []),
                highlights=highlights,
            )
            reflection = await invoke_structured(
                build_greeting_reflection_prompt(
                    company_name=company_name,
                    job_title=job_title,
                    jd_text=jd_summary[:500],
                    highlights_text=highlights_text,
                    greetings_json=json.dumps(greetings, ensure_ascii=False),
                ),
                GreetingReflectionOutput,
                api_config,
                channel="reflector",
                temperature=0.0,
                max_retries=1,
                deadline=deadline,
                call_metadata={
                    **dict(call_metadata or {}),
                    "stage": f"greeting.reflect.{round_index + 1}",
                    "reflection_round": round_index + 1,
                },
            )
            if not deterministic_issues and reflection.approved and all((
                reflection.truthfulness_pass,
                reflection.relevance_pass,
                reflection.length_pass,
            )):
                logger.info(
                    "[GreetingGenerator] 生成并通过自审: count=%s round=%s",
                    len(greetings),
                    round_index + 1,
                )
                return greetings
            if round_index == 0:
                issues = [*deterministic_issues, *reflection.issues][:8]
                if not issues:
                    issues = ["真实性、相关性或长度契约未全部通过"]
                reflection_text = (
                    "\n【上轮自审反馈 - 必须逐项修正】\n"
                    + "\n".join(f"- {item}" for item in issues)
                )
                continue
            raise ValueError("greeting reflection rejected the second draft")
    except Exception as exc:
        logger.error("[GreetingGenerator] 生成或自审失败: %s", type(exc).__name__)
        return _generate_fallback_greetings(company_name, job_title, highlights)


def _validate_generated_greetings(
    raw_greetings: list[dict[str, Any]],
    *,
    highlights: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return normalized drafts plus deterministic issues that the reflector must not override."""
    by_tone = {str(item.get("tone") or ""): dict(item) for item in raw_greetings}
    expected_tones = ("professional", "technical", "result_oriented")
    if any(tone not in by_tone for tone in expected_tones):
        raise ValueError("greeting tones are incomplete")
    greetings = [by_tone[tone] for tone in expected_tones]
    issues: list[str] = []

    for greeting in greetings:
        tone = str(greeting.get("tone") or "unknown")
        message_text = str(greeting.get("message_text") or "").strip()
        greeting["message_text"] = message_text
        if "您的项目" in message_text or "欢迎深入沟通" in message_text:
            issues.append(f"{tone} 使用了招聘方口吻")
        if "我" not in message_text:
            issues.append(f"{tone} 缺少候选人第一人称主体")
        if not 100 <= len(message_text) <= 220:
            issues.append(f"{tone} 不满足 100-220 字长度契约")
        unsupported = [
            item
            for item in greeting.get("highlights_used", [])
            if not claim_has_evidence(str(item), highlights)
        ]
        if unsupported:
            issues.append(f"{tone} 使用了未提供的候选人亮点")
            greeting["risk_notes"] = (
                str(greeting.get("risk_notes") or "") + " [需复核] 使用了未提供的亮点"
            ).strip()
    return greetings, issues


def _generate_fallback_greetings(
    company_name: str,
    job_title: str,
    highlights: list[str] | None = None,
) -> List[Dict[str, Any]]:
    """模型失败时只使用传入的真实亮点，生成三条可编辑的第一人称文案。"""
    company = (company_name or "贵司")[:40]
    role = (job_title or "目标岗位")[:40]
    evidence = list(highlights or [])[:3]
    evidence_text = evidence[0][:70] if evidence else "我会基于简历中的真实项目经历说明自己与岗位要求的对应关系"
    used = evidence[:1]
    risk_note = "[兜底文案] 模型生成失败，请在发送前结合岗位与简历复核"
    return [
        {
            "tone": "professional",
            "message_text": f"您好，我关注到{company}正在招聘{role}。{evidence_text}。我希望把已有经验用于岗位中的实际业务和协作场景，也愿意进一步说明我承担的职责、使用的方法和可验证结果。希望有机会与您沟通岗位重点及团队当前需求。",
            "highlights_used": used,
            "risk_notes": risk_note,
        },
        {
            "tone": "technical",
            "message_text": f"您好，我对{company}的{role}岗位很感兴趣。{evidence_text}。我关注工程实现、接口边界、可维护性和交付质量，也希望结合岗位描述进一步介绍我的技术取舍与问题解决过程。希望有机会了解团队技术栈、核心场景和当前挑战。",
            "highlights_used": used,
            "risk_notes": risk_note,
        },
        {
            "tone": "result_oriented",
            "message_text": f"您好，我正在关注{company}的{role}岗位。{evidence_text}。我习惯围绕业务目标拆解任务，并用真实项目中的职责、过程和结果说明自己的贡献；如果方向合适，我可以继续补充与岗位最相关的案例。希望有机会进一步沟通团队业务。",
            "highlights_used": used,
            "risk_notes": risk_note,
        },
    ]
