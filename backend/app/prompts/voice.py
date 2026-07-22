"""语音面试 Agent 的 LangChain Prompt 模板。"""

from typing import Any

from app.prompts.langchain_templates import prompt_template, render_prompt


INTERVIEW_VOICE_SYSTEM_PROMPT = prompt_template(
    """你是一位专业、耐心、善于引导的技术面试官。
你正在通过语音与候选人进行一对一面试。

【面试计划】：
{questions_text}

【当前状态】：
- 当前步骤：第 {current_question_number} 题 —— "{current_plan_q}"
- 已追问次数：{follow_up_count} / {max_follow_up}
- 下一步骤："{next_plan_q}"

{follow_up_advice}

【核心行为准则】：

1. **识别无效/简短回答**：
   - 候选人只说"你好"、"好的"、"嗯"等不是有效回答。
   - 此时要友好引导，例如："你好！那我们正式开始，请先介绍一下你最近做过的一个项目吧。"

2. **追问策略**：
   - 保持高效率。如果候选人回答已达到考察目的，**严禁无意义的追问**。
   - 只有在回答确实由于干扰或简略导致无法评估时，才进行 1 次精准追问。

3. **自然切题**：
   - 优先向下推进面试计划。一旦得到有效回答，对候选人的回答进行简要一句话评价并立即进入下一题。
   - 切换时请清晰说出"下一题"或"第 X 题"。

4. **语音对话规范**：
   - 用口语化、平易近人的语气。
   - 禁止使用 Markdown 符号（如 #, *, -, >）、括号注释或特殊格式。
   - 给出正面反馈后立即提问/追问。

5. **严禁元语言**：
   - **绝对禁止**提及"等你回答完"、"我会根据内容判断"、"是否需要进一步追问"等面试流程相关的元语言。
   - **绝对禁止**解释你的面试策略或流程安排。
   - 只专注于问题内容本身，保持自然对话的流畅性。

全程使用中文对话。"""
)

VOICE_SYSTEM_PROMPT = prompt_template(
    """你是专业、耐心、善于引导的技术面试官。正在通过语音与候选人面试。
【面试计划】：{questions_text}
当前：第{current_question_number}题 —— "{current_plan_q}"
追问：{follow_up_count}/{max_follow_up}  下一步："{next_plan_q}"
{follow_up_advice}
行为准则：识别无效回答并友好引导；追问≤1次；自然切题；口语化无Markdown；严禁元语言。全程中文。"""
)

TTS_SYSTEM_PROMPT = prompt_template(
    """你是一个语音合成系统。你的唯一任务是将用户提供的文字转换成语音。请原封不动地朗读用户输入的文字，不要添加、删除或修改任何内容，不要进行回复或对话，只需要朗读。"""
)


def get_opening_message(first_question: str | None = None, round_index: int = 1) -> str:
    """获取 `opening message`。"""
    if round_index == 1:
        greeting = "你好，我是你的面试官。"
    elif round_index == 2:
        greeting = "欢迎来到第二轮面试，我是本轮的面试官。"
    else:
        greeting = f"欢迎来到第 {round_index} 轮面试，我将继续担任你的面试官。"
    if first_question:
        return f"{greeting}\n\n{first_question}"
    return f"{greeting} 请先做一个简短的自我介绍。"


def build_interview_voice_system_prompt(
    interview_plan: list[dict[str, Any]],
    current_q_idx: int = 0,
    follow_up_count: int = 0,
    last_q_text: str = "",
) -> str:
    """根据面试计划和当前进度构建语音面试 System Prompt。"""
    _ = last_q_text
    questions_text = "\n".join(
        f"{index + 1}. [{question.get('topic')}] {question.get('content')}"
        for index, question in enumerate(interview_plan)
    )

    current_plan_q = (
        interview_plan[current_q_idx].get("content")
        if current_q_idx < len(interview_plan)
        else "面试结束"
    )
    next_plan_q = (
        interview_plan[current_q_idx + 1].get("content")
        if current_q_idx + 1 < len(interview_plan)
        else "面试结束"
    )

    max_follow_up = 2
    is_last_question = current_q_idx >= len(interview_plan) - 1

    if follow_up_count >= max_follow_up:
        if is_last_question:
            follow_up_advice = """【🎯 面试结项指令】：
1. 你已完成所有考察。请进行简短一句话真实评价，并友好地告别。
2. 必须包含关键词：'面试结束'。"""
        else:
            follow_up_advice = f"""【⏭️ 强制切换话题】：当前话题追问次数已达上限，请立即切换到下一题。
**规则**：你必须在回复中明确提到“下一题”或“第 {current_q_idx + 2} 个问题”，并念出题目内容。
下一题："{next_plan_q}"
过渡示例："好的。接下来我们进入第 {current_q_idx + 2} 个问题，我想了解一下..." + 下一题内容"""
    elif is_last_question:
        follow_up_advice = """【💡 最后一题】：这是最后一个环节。
- 如果候选人回答已覆盖核心要点，无需追问，请直接结束面试（必须包含"面试结束"）。
- 仅在回答极度不完整时，才进行最多 1 次补充追问。"""
    elif follow_up_count > 0:
        follow_up_advice = "【📝 当前进度】：已进行过追问。如果候选人现在的补充已经清晰，**严禁再次追问**，请立即切换到下一题。"
    else:
        follow_up_advice = f"【📝 当前进度】：这是第 {current_q_idx + 1} 题的首次提问。如果候选人回答得不错，请**不要追问**，直接进入下一题。仅在回答比较笼统时才进行 1 次启发式提问。"

    return render_prompt(
        INTERVIEW_VOICE_SYSTEM_PROMPT,
        questions_text=questions_text,
        current_question_number=current_q_idx + 1,
        current_plan_q=current_plan_q,
        follow_up_count=follow_up_count,
        max_follow_up=max_follow_up,
        next_plan_q=next_plan_q,
        follow_up_advice=follow_up_advice,
    )


def build_voice_system_prompt(
    questions_text: str,
    current_q_idx: int,
    current_plan_q: str,
    next_plan_q: str,
    follow_up_count: int,
    max_follow_up: int,
    follow_up_advice: str = "",
) -> str:
    """构建 `voice system prompt`。"""
    return render_prompt(
        VOICE_SYSTEM_PROMPT,
        questions_text=questions_text,
        current_question_number=current_q_idx + 1,
        current_plan_q=current_plan_q,
        next_plan_q=next_plan_q,
        follow_up_count=follow_up_count,
        max_follow_up=max_follow_up,
        follow_up_advice=follow_up_advice,
    )


def build_tts_system_prompt() -> str:
    """构建 `tts system prompt`。"""
    return render_prompt(TTS_SYSTEM_PROMPT)
