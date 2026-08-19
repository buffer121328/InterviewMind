"""能力分析 Agent 的 LangChain Prompt 模板。"""

from ai.prompts.langchain_templates import prompt_template, render_prompt
from ai.prompts.shared import (
    CONCISE_CHINESE_RULES,
    EVIDENCE_RULES,
    SCORE_CALIBRATION_RULES,
    STRICT_JSON_RULES,
    UNTRUSTED_INPUT_RULES,
)

SESSION_REPORT_PROMPT = prompt_template(
    f"""你是资深技术面试官和面试复盘专家。请基于同一份真实证据，一次生成本场逐题证据、能力画像和短板地图。

{UNTRUSTED_INPUT_RULES}
{EVIDENCE_RULES}
{SCORE_CALIBRATION_RULES}
{CONCISE_CHINESE_RULES}

【已预算化报告上下文】
{{report_context}}

【回答要点使用边界】
上下文中的 answer_points 或“内部评分参考”只用于判断回答覆盖度和缺口；不得在最终 question_evidence、question_failures、能力画像或短板报告中新增回答要点字段，也不得把内部要点当作候选人已经说过的事实。

【输出要求】
1. 顶层必须包含 question_evidence、candidate_profile 和 weakness_report，不得省略 candidate_profile 或 weakness_report。
2. question_evidence 按 Q1、Q2 顺序记录 question_id、topic、question_summary、candidate_claims、demonstrated_skills、missing_evidence、communication_observations、score_or_signal；不得写入原问答没有出现的事实。
3. candidate_profile 评估 professional_competence、execution_results、logic_problem_solving、communication、growth_potential、collaboration 六个维度，均为 0-10 分；每个 evidence 和 reason 必须引用一个或多个 [Qn]。
4. candidate_profile.skill_tags 提取 5-10 个有证据的技能；key_strengths 和 key_weaknesses 各 1-5 条；recommendation 只能是 strong_hire、hire、borderline 或 no_hire。
5. weakness_report.weakness_categories 最多 4 类，只能使用：基础概念、项目表达、系统设计、行为面试、沟通表达、压力应对。description 必须引用 [Qn]，severity 只能是 high、medium、low。
6. weakness_report.question_failures 选择 2-3 个有真实问答证据的薄弱回答；不得把未回答问题算作能力缺陷。
7. weakness_report.improvement_actions 给出 3-6 个动作，priority 为 1-5 且 1 最高，estimated_effort 使用 1天、1周、2周或1月。
8. weakness_report.question_evidence 与顶层 question_evidence 使用相同题号和事实口径。
9. 所有结论必须能回溯到 question_evidence，不得在画像和短板地图之间产生矛盾。

{STRICT_JSON_RULES}"""
)

EVIDENCE_CHUNK_PROMPT = prompt_template(
    f"""你是面试证据归档器。请把下面连续问答转换成逐题证据，不生成最终画像或录用建议。

{UNTRUSTED_INPUT_RULES}
{EVIDENCE_RULES}
{CONCISE_CHINESE_RULES}

【问答块】
{{qa_text}}

【回答要点使用边界】
问答块中的 answer_points 仅供内部判断回答覆盖度；candidate_claims 只能来自候选人真实回答，输出不得回显回答要点列表。

【要求】
1. 输出 items 数量必须与问答数量一致，并沿用输入中的 Qn 作为 question_id。
2. candidate_claims 只摘录或忠实概括候选人明确表达的事实；不得补写数字、职责或技术栈。
3. demonstrated_skills 只记录回答直接展示的技能；证据不足时使用空数组。
4. missing_evidence 只描述回答本身缺少的验证要素，不推断候选人不具备该能力。
5. 每个文本字段保持简洁，单项不超过 160 字。

输出结构：{{output_schema}}
{STRICT_JSON_RULES}"""
)

EVIDENCE_REPORT_PROMPT = prompt_template(
    f"""你是资深技术面试官和面试复盘专家。请只基于已归档逐题证据生成能力画像和短板地图。

{UNTRUSTED_INPUT_RULES}
{EVIDENCE_RULES}
{SCORE_CALIBRATION_RULES}
{CONCISE_CHINESE_RULES}

【岗位与候选人上下文】
{{report_context}}

【已归档逐题证据，共 {{evidence_count}} 题】
{{evidence_text}}

【要求】
1. 顶层包含 question_evidence、candidate_profile 和 weakness_report；question_evidence 原样按题号复述，不增加事实。
2. 六个能力维度的 evidence、reason、key_strengths、key_weaknesses 和短板 description 必须引用 [Qn]。
3. 没有证据的能力保持保守评价，不得用简历内容替代面试表现。
4. recommendation 只能是 strong_hire、hire、borderline 或 no_hire；所有短板和改进项使用同一证据口径。
5. weakness_report.question_evidence 与顶层 question_evidence 使用相同题号。

{STRICT_JSON_RULES}"""
)

MULTI_REVIEWER_PROMPT = prompt_template(
    f"""你是多智能体评估中的独立评审者，当前视角为 {{perspective_name}}。只从该视角审查，不替其他角色下结论。

{UNTRUSTED_INPUT_RULES}
{EVIDENCE_RULES}
{SCORE_CALIBRATION_RULES}
{CONCISE_CHINESE_RULES}

【评估类型】{{mode_name}}
【当前视角职责】
{{perspective_instruction}}

【共享且已预算化的只读上下文】
{{review_context}}

【回答要点使用边界】
若上下文包含 answer_points，它们只是内部评分基准，不是候选人事实；可用于识别覆盖点和缺口，但不得在评审输出中原样回显或扩写为候选人证据。

【独立评审规则】
1. score 为当前视角 0-10 分；证据不足时保守评分并降低 confidence，不得用常识补事实。
2. dimension_scores 只填写当前视角能够直接判断的维度，值均为 0-10；不要为了完整而猜测。
3. strengths、concerns 各最多 5 条，evidence_refs 使用 [Qn]、历史序号或上下文中的明确证据定位。
4. 不参考其他评审者，也不要生成最终录用结论；输出中 perspective 必须是 {{perspective_key}}。

输出结构：{{output_schema}}
{STRICT_JSON_RULES}"""
)

MULTI_REVIEWER_CONSENSUS_PROMPT = prompt_template(
    f"""你是多智能体评估的共识汇总者。请综合相互独立的评审结果，解决分歧并生成唯一最终报告。

{UNTRUSTED_INPUT_RULES}
{EVIDENCE_RULES}
{SCORE_CALIBRATION_RULES}
{CONCISE_CHINESE_RULES}

【评估类型】{{mode_name}}
{{consensus_context_section}}

【独立评审结果】
{{reviewer_outputs}}

【汇总规则】
1. 不做简单平均：优先采用有明确证据、置信度更高且职责匹配的判断；分歧必须采取保守口径。
2. factual_risk 指出的无证据事实不得进入优势、技能或推荐理由；评审失败项只降低置信度，不得伪造替代意见。
3. {{consensus_instruction}}
4. 最终结论必须可回溯到共享上下文或评审 evidence_refs，不输出评审者内部推理过程。

{STRICT_JSON_RULES}"""
)

def build_session_report_prompt(
    report_context: str,
) -> str:
    """构建会话报告提示词相关后端逻辑。"""
    return render_prompt(
        SESSION_REPORT_PROMPT,
        prompt_name="analysis.session_report",
        prompt_version="2",
        report_context=report_context,
    )


def build_evidence_chunk_prompt(qa_text: str) -> str:
    """构建证据片段提示词相关后端逻辑。"""
    return render_prompt(
        EVIDENCE_CHUNK_PROMPT,
        prompt_name="analysis.question_evidence",
        prompt_version="1",
        qa_text=qa_text,
        output_schema=(
            '{"items":[{"question_id":"Q1","topic":"主题","question_summary":"问题摘要",'
            '"candidate_claims":[],"demonstrated_skills":[],"missing_evidence":[], '
            '"communication_observations":[],"score_or_signal":null}]}'
        ),
    )


def build_evidence_report_prompt(
    *,
    report_context: str,
    evidence_text: str,
    evidence_count: int,
) -> str:
    """构建证据报告提示词相关后端逻辑。"""
    return render_prompt(
        EVIDENCE_REPORT_PROMPT,
        prompt_name="analysis.evidence_report",
        prompt_version="1",
        report_context=report_context,
        evidence_text=evidence_text,
        evidence_count=evidence_count,
    )


def build_multi_reviewer_prompt(*, mode: str, perspective: str, review_context: str) -> str:
    """构建多评审提示词相关后端逻辑。"""
    perspective_instructions = {
        "technical_depth": "评估技术原理深度、方案取舍、问题拆解和实现可信度；重点关注专业能力与逻辑问题解决。",
        "communication": "评估回答结构、清晰度、信息密度、倾听与协作表达；不要把技术正确性替代为表达分。",
        "job_fit": "对照岗位要求评估技能、经历和职责匹配；区分硬性要求、加分项和证据缺口。",
        "factual_risk": "以对抗性验证者身份寻找事实跳跃、证据不足、前后矛盾和过度推断；宁可保守，不替候选人补证据。",
    }
    mode_name = "单场面试复盘" if mode == "session_report" else "跨场综合能力画像"
    return render_prompt(
        MULTI_REVIEWER_PROMPT,
        prompt_name=f"analysis.multi_reviewer.{perspective}",
        prompt_version="1",
        perspective_name=perspective,
        perspective_key=perspective,
        perspective_instruction=perspective_instructions[perspective],
        mode_name=mode_name,
        review_context=review_context,
        output_schema=(
            '{"perspective":"technical_depth","score":7.5,"dimension_scores":{},'
            '"strengths":[],"concerns":[],"evidence_refs":[],"confidence":0.8,'
            '"status":"success","error_type":null}'
        ),
    )


def build_multi_reviewer_consensus_prompt(*, mode: str, review_context: str, reviewer_outputs: str) -> str:
    """构建多评审共识提示词相关后端逻辑。"""
    if mode == "session_report":
        instruction = (
            "输出完整 SessionInterviewReportOutput：保留逐题证据，六维画像分数为 0-10，"
            "短板、优势和推荐必须口径一致并引用 [Qn]。"
        )
        mode_name = "单场面试复盘"
        consensus_context_section = (
            "【输入边界】本次仅提供四位独立评审的结构化结论；"
            "不得假设、补充或追问原始 QA、简历、JD、公司信息、逐题证据或内部回答要点。"
        )
        prompt_version = "2"
    else:
        instruction = (
            "数值维度已由本地时间加权算法确定，不得改写；只输出综合评价、优势、短板、"
            "recommendation 和 0-1 confidence。"
        )
        mode_name = "跨场综合能力画像"
        consensus_context_section = f"【原始只读上下文】\n{review_context}"
        prompt_version = "1"
    return render_prompt(
        MULTI_REVIEWER_CONSENSUS_PROMPT,
        prompt_name=f"analysis.multi_reviewer_consensus.{mode}",
        prompt_version=prompt_version,
        mode_name=mode_name,
        consensus_context_section=consensus_context_section,
        reviewer_outputs=reviewer_outputs,
        consensus_instruction=instruction,
    )


def build_technical_depth_reviewer_prompt(review_context: str) -> str:
    """构建评审提示词相关后端逻辑。"""
    return build_multi_reviewer_prompt(mode="session_report", perspective="technical_depth", review_context=review_context)


def build_communication_reviewer_prompt(review_context: str) -> str:
    """构建评审提示词相关后端逻辑。"""
    return build_multi_reviewer_prompt(mode="session_report", perspective="communication", review_context=review_context)


def build_job_fit_reviewer_prompt(review_context: str) -> str:
    """构建岗位评审提示词相关后端逻辑。"""
    return build_multi_reviewer_prompt(mode="session_report", perspective="job_fit", review_context=review_context)


def build_factual_risk_reviewer_prompt(review_context: str) -> str:
    """构建评审提示词相关后端逻辑。"""
    return build_multi_reviewer_prompt(mode="session_report", perspective="factual_risk", review_context=review_context)


def build_session_review_consensus_prompt(review_context: str, reviewer_outputs: str) -> str:
    """构建会话复核共识提示词相关后端逻辑。"""
    return build_multi_reviewer_consensus_prompt(mode="session_report", review_context=review_context, reviewer_outputs=reviewer_outputs)


def build_ability_review_consensus_prompt(review_context: str, reviewer_outputs: str) -> str:
    """构建能力复核共识提示词相关后端逻辑。"""
    return build_multi_reviewer_consensus_prompt(mode="ability_profile", review_context=review_context, reviewer_outputs=reviewer_outputs)
