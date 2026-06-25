"""面试对话 Agent 的 Prompt 模板"""
from typing import Optional

def memo_hint(memory_context: str) -> str:
    if not memory_context:
        return ""
    return f"""
【候选人背景参考（不要直接泄露记忆来源）】：
{memory_context}
"""

def build_planner_prompt(round_index, round_type, max_questions, job_description="", company_info="",
                         resume="", previous_questions_section="", weakness_section="", rag_section="",
                         memory_section="", strategy_focus="", requirements="", output_format="full"):
    company_section = ""
    if company_info and company_info != "未知":
        company_section = f"\n【目标公司】：\n{company_info}"
    json_format = (
        '```json\n[\n  {"topic":"...","content":"..."}\n]\n只返回 JSON 数组。```'
        if output_format == "simple" else
        '{"questions":[{"id":1,"topic":"考察主题","content":"具体问题","type":"intro/tech/behavior",'
        '"sources":[],"reason":"为什么问","fallback_reason":null}]}'
    )
    return f"""你是一位资深面试官。这是第 {round_index} 轮面试（类型：{round_type}）。设计 {max_questions} 道题目。
【岗位描述】：{job_description or "未提供"}{company_section}
【简历】：{resume or "未提供"}{previous_questions_section}{weakness_section}{rag_section}{memory_section}
【侧重点】：{strategy_focus}  要求：{requirements}
输出纯 JSON：{json_format}"""

def build_hints_prompt(questions_text: str) -> str:
    return f"""你是面试辅导专家。为以下问题生成回答提示（50-100字/题）。
{questions_text}
输出 JSON：{{"hints": ["提示1", "提示2"]}}"""

def build_opening_prompt(round_index, round_type, strategy_focus, first_question, memory_context=""):
    return f"""你是专业面试官，第 {round_index} 轮（侧重：{strategy_focus}）。
请输出开场问候语并自然过渡到第一题。
【第一题】：{first_question}
要求：开场1-2句，自然引出题目，50字以内。{memo_hint(memory_context)}"""

def build_evaluating_prompt(round_index, round_type, strategy_focus, current_index, total_questions,
                            current_question, next_question, follow_up_count, max_follow_ups,
                            user_answer, tool_context="", memory_context=""):
    return f"""你是技术面试官。第 {round_index} 轮（侧重：{strategy_focus}）。
进度：第 {current_index + 1}/{total_questions} 题
当前题：{current_question}  下一题：{next_question or '已是最后一题'}
追问：{follow_up_count}/{max_follow_ups}
回答：{user_answer}
{tool_context}
任务：1.评价回答（一句）2.决策：follow_up(追问<{max_follow_ups})/advance(过渡到下一题)/end_round
原则：追问仅深挖细节；切换到下一题必须完整复述原文；最后一题且回答充分则 end_round
{memo_hint(memory_context)}"""

def build_feedback_prompt() -> str:
    return """面试结束。请生成反馈报告：
1. 综合评分(0-100)
2. 主要优点(1-3条)
3. 主要不足(2-3条)
4. 面试建议(1-3条)
简洁专业。"""
