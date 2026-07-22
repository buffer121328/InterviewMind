"""面试对话 Agent 的 LangChain Prompt 模板。"""

from app.prompts.langchain_templates import prompt_template, render_prompt


MEMO_HINT_PROMPT = prompt_template(
    """
【候选人背景参考（不要直接泄露记忆来源）】：
{memory_context}
"""
)

PLANNER_PROMPT = prompt_template(
    """你是一位资深面试官。这是第 {round_index} 轮面试（类型：{round_type}）。设计 {max_questions} 道题目。
【岗位描述】：{job_description}{company_section}
【简历】：{resume}{previous_questions_section}{weakness_section}{rag_section}{memory_section}
【侧重点】：{strategy_focus}  要求：{requirements}
输出纯 JSON：{json_format}"""
)

HINTS_PROMPT = prompt_template(
    """你是面试辅导专家。为以下问题生成回答提示（50-100字/题）。
{questions_text}
输出 JSON：{output_schema}"""
)

OPENING_PROMPT = prompt_template(
    """你是专业面试官，第 {round_index} 轮（侧重：{strategy_focus}）。
请输出开场问候语并自然过渡到第一题。
【第一题】：{first_question}
要求：开场1-2句，自然引出题目，50字以内。{memory_hint}"""
)

EVALUATING_PROMPT = prompt_template(
    """你是技术面试官。第 {round_index} 轮（侧重：{strategy_focus}）。
进度：第 {current_question_number}/{total_questions} 题
当前题：{current_question}  下一题：{next_question}
追问：{follow_up_count}/{max_follow_ups}
回答：{user_answer}
{tool_context}
任务：1.评价回答（一句）2.决策：follow_up(追问<{max_follow_ups})/advance(过渡到下一题)/end_round
原则：追问仅深挖细节；切换到下一题必须完整复述原文；最后一题且回答充分则 end_round
{memory_hint}"""
)

FEEDBACK_PROMPT = prompt_template(
    """面试结束。请生成反馈报告：
1. 综合评分(0-100)
2. 主要优点(1-3条)
3. 主要不足(2-3条)
4. 面试建议(1-3条)
简洁专业。"""
)


def memo_hint(memory_context: str) -> str:
    """构建记忆提示片段。"""
    if not memory_context:
        return ""
    return render_prompt(MEMO_HINT_PROMPT, memory_context=memory_context)


def build_planner_prompt(
    round_index,
    round_type,
    max_questions,
    job_description="",
    company_info="",
    resume="",
    previous_questions_section="",
    weakness_section="",
    rag_section="",
    memory_section="",
    strategy_focus="",
    requirements="",
    output_format="full",
):
    """构建 `planner prompt`。"""
    company_section = ""
    if company_info and company_info != "未知":
        company_section = f"\n【目标公司】：\n{company_info}"
    json_format = (
        '```json\n[\n  {"topic":"...","content":"..."}\n]\n只返回 JSON 数组。```'
        if output_format == "simple"
        else '{"questions":[{"id":1,"topic":"考察主题","content":"具体问题","type":"intro/tech/behavior","sources":[],"reason":"为什么问","fallback_reason":null}]}'
    )
    return render_prompt(
        PLANNER_PROMPT,
        round_index=round_index,
        round_type=round_type,
        max_questions=max_questions,
        job_description=job_description or "未提供",
        company_section=company_section,
        resume=resume or "未提供",
        previous_questions_section=previous_questions_section,
        weakness_section=weakness_section,
        rag_section=rag_section,
        memory_section=memory_section,
        strategy_focus=strategy_focus,
        requirements=requirements,
        json_format=json_format,
    )


def build_hints_prompt(questions_text: str) -> str:
    """构建 `hints prompt`。"""
    return render_prompt(
        HINTS_PROMPT,
        questions_text=questions_text,
        output_schema='{"hints": ["提示1", "提示2"]}',
    )


def build_opening_prompt(round_index, round_type, strategy_focus, first_question, memory_context=""):
    """构建 `opening prompt`。"""
    _ = round_type
    return render_prompt(
        OPENING_PROMPT,
        round_index=round_index,
        strategy_focus=strategy_focus,
        first_question=first_question,
        memory_hint=memo_hint(memory_context),
    )


def build_evaluating_prompt(
    round_index,
    round_type,
    strategy_focus,
    current_index,
    total_questions,
    current_question,
    next_question,
    follow_up_count,
    max_follow_ups,
    user_answer,
    tool_context="",
    memory_context="",
):
    """构建 `evaluating prompt`。"""
    _ = round_type
    return render_prompt(
        EVALUATING_PROMPT,
        round_index=round_index,
        strategy_focus=strategy_focus,
        current_question_number=current_index + 1,
        total_questions=total_questions,
        current_question=current_question,
        next_question=next_question or "已是最后一题",
        follow_up_count=follow_up_count,
        max_follow_ups=max_follow_ups,
        user_answer=user_answer,
        tool_context=tool_context,
        memory_hint=memo_hint(memory_context),
    )


def build_feedback_prompt() -> str:
    """构建 `feedback prompt`。"""
    return render_prompt(FEEDBACK_PROMPT)
