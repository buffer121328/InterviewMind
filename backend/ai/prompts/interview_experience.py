"""面经候选题质量治理提示词。"""

from ai.prompts.langchain_templates import prompt_template, render_prompt
from ai.prompts.shared import (
    CONCISE_CHINESE_RULES,
    EVIDENCE_RULES,
    STRICT_JSON_RULES,
    UNTRUSTED_INPUT_RULES,
)

EXPERIENCE_GOVERNANCE_PROMPT = prompt_template(
    f"""你是面试题库质量审核员。请逐条审核输入候选题，且必须为每个 candidate_index 返回一个决定。

{UNTRUSTED_INPUT_RULES}
{EVIDENCE_RULES}
{CONCISE_CHINESE_RULES}

【候选题】
{{candidate_payload}}

【审核规则】
1. 陈述句、上下文残片、重复题、依赖缺失上下文才能理解的题、过度宽泛或无法形成有效考察的内容设置 keep=false。
2. keep=true 时可以修正明显的口语残缺，但不得改变题意或创造候选中不存在的新题。
3. keep=true 时生成 2-5 条中文 answer_points；技术题覆盖原理、边界、方案和验证，行为题覆盖情境、行动、结果和复盘。
4. question_type 只能是 intro、tech、behavior、system_design；difficulty 只能是 easy、medium、hard。
5. tags 最多 10 个，target_skill 只填写题目可直接证明的核心技能；无法判断时为空。
6. keep=false 时保留原 candidate_index，answer_points 可为空，并用 rejection_reason 简述原因。
7. 不得遗漏、增加或重复 candidate_index。

【输出结构】
{{output_schema}}

{STRICT_JSON_RULES}"""
)


def build_experience_governance_prompt(candidate_payload: str) -> str:
    """Render the bounded structured-review prompt without executing a model call."""
    return render_prompt(
        EXPERIENCE_GOVERNANCE_PROMPT,
        prompt_name="interview.experience_governance",
        prompt_version="1",
        candidate_payload=candidate_payload,
        output_schema=(
            '{"questions":[{"candidate_index":0,"keep":true,'
            '"question_text":"规范后的原题","answer_points":["要点1","要点2"],'
            '"tags":["标签"],"difficulty":"easy/medium/hard",'
            '"target_skill":"技能或null","question_type":"intro/tech/behavior/system_design",'
            '"rejection_reason":null}]}'
        ),
    )
