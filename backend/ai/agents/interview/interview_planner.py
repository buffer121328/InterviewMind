"""
面试规划统一模块
将 voice_interview.py 和 graph.py 中的规划逻辑抽离复用
"""

import json
import logging
from typing import List, Dict, Any, Optional

from app.schemas.llm_outputs import PlanOutput, SimplePlanOutput, HintOutput
from ai.llm.llm_utils import invoke_structured, clean_json_response

logger = logging.getLogger(__name__)


# ============================================================================
# 轮次策略定义
# ============================================================================

ROUND_STRATEGIES = {
    "tech_initial": {
        "name": "综合面",
        "focus": "基础专业能力、项目概述、行为面试题、综合素质初评",
        "requirements": """
    1. 第 1 道为自我介绍题。
    2. 重点考察简历中提到的核心技能和专业知识，覆盖广度而非深度。
    3. 至少包含 1 道行为面试题（如：团队合作、解决冲突的经历）。
    4. 题目难度适中，建立基础素质基线。
    5. 每道题应该是独立的、具体的问题，不要一道题包含过多子问题。"""
    },
    "tech_deep": {
        "name": "技术面",
        "focus": "深挖简历项目细节、系统设计能力、技术原理追问、案例分析",
        "requirements": """
    1. 不需要自我介绍，直接进入专业深度问题。
    2. 【重要】基于简历中的具体项目或工作经历进行深挖，不要出全新的宏大开放题。
    3. 从简历已有内容延伸，逐步深入到专业原理、系统设计和复杂度层面。
    4. 可以包含 1 道中等规模的案例分析或方案设计题。
    5. 重点验证项目细节的真实性和技术深度的界限。
    6. 每道题聚焦单一知识点或能力维度，避免一道题问太多内容。"""
    },
    "hr_comprehensive": {
        "name": "HR面",
        "focus": "职业规划、软技能、文化匹配度、薪资期望、综合素质终评",
        "requirements": """
    1. 可以包含 1 道综合性案例题（考察全局分析和方案设计能力）。
    2. 至少包含 2 道行为面试题（考察领导力、抗压能力、职业规划等）。
    3. 考察候选人的沟通表达、价值观和文化匹配度。
    4. 可以出开放性问题，考察候选人的思维广度和深度。
    5. 关注候选人的职业发展规划和成长潜力。"""
    },
    # 语音面试专用：简化版，不区分轮次
    "voice_default": {
        "name": "语音面试",
        "focus": "全面考察候选人能力",
        "requirements": """
    1. 自我介绍/职业规划
    2. 技术深度（针对简历中的项目经验）
    3. 问题解决能力
    4. 团队协作与沟通
    5. 岗位匹配度"""
    }
}


# ============================================================================
# 默认问题（兜底方案）
# ============================================================================

DEFAULT_QUESTIONS = [
    {"id": 1, "topic": "自我介绍", "content": "请做一个简短的自我介绍，包括你的教育背景和工作经历。", "type": "intro"},
    {"id": 2, "topic": "项目经验", "content": "请介绍一个你最有成就感的项目。", "type": "tech"},
    {"id": 3, "topic": "技术能力", "content": "你最擅长的技术栈是什么？", "type": "tech"},
    {"id": 4, "topic": "问题解决", "content": "请描述一个你解决过的技术难题。", "type": "behavior"},
    {"id": 5, "topic": "职业规划", "content": "你对未来的职业发展有什么规划？", "type": "behavior"}
]


# ============================================================================
# Prompt 构建器
# ============================================================================

def build_planner_prompt(
    resume: str,
    job_description: str,
    company_info: str,
    max_questions: int,
    round_type: str = "tech_initial",
    round_index: int = 1,
    previous_profile: Optional[Dict] = None,
    previous_questions: Optional[List[str]] = None,
    output_format: str = "full",
    weakness_report: Optional[Dict] = None,
    retrieval_context: Optional[Dict] = None,
    memory_context: Optional[str] = None,
) -> str:
    """Build the interview plan through the central evidence-bounded template."""
    from ai.prompts.interview import build_planner_prompt as build_central_planner_prompt

    strategy = ROUND_STRATEGIES.get(round_type, ROUND_STRATEGIES["tech_initial"])
    requirements = strategy["requirements"]
    if round_type == "tech_deep" and previous_profile:
        assessment = str(previous_profile.get("overall_assessment", ""))[:300]
        if assessment:
            requirements += f"\n上一轮评估参考：{assessment}"

    previous_questions_section = ""
    if previous_questions:
        previous_questions_section = "【上一轮已问过的问题（请勿重复）】\n" + "\n".join(
            f"- {question}" for question in previous_questions
        )

    weakness_section = ""
    categories = (weakness_report or {}).get("weakness_categories", [])
    if categories:
        weakness_section = "【上一轮短板，仅用于调整考察角度】\n" + "\n".join(
            f"- [{item.get('severity', 'medium')}] {item.get('category', '')}: {item.get('description', '')}"
            for item in categories[:4]
        )

    rag_section = ""
    if retrieval_context:
        evidences = retrieval_context.get("rag_evidences", [])
        if evidences:
            rag_section = "【检索证据】\n" + "\n".join(
                f"- [{item.get('source_type', '')}] {item.get('evidence', '')[:160]}"
                for item in evidences[:6]
            )
        else:
            bank_questions = retrieval_context.get("bank_questions", [])
            if bank_questions:
                rag_section = "【题库参考，仅作灵感且不得照抄】\n" + "\n".join(
                    f"- [{item.get('difficulty', 'medium')}] {item.get('question_text', '')}"
                    for item in bank_questions[:4]
                )

    memory_section = ""
    if memory_context:
        memory_section = (
            "【候选人长期记忆】\n"
            + memory_context[:3000]
            + "\n请用于调整侧重点，但不要直接泄露记忆来源。"
        )

    return build_central_planner_prompt(
        round_index=round_index,
        round_type=round_type,
        max_questions=max_questions,
        job_description=job_description or "未提供",
        company_info=company_info,
        resume=resume or "未提供",
        previous_questions_section=previous_questions_section,
        weakness_section=weakness_section,
        rag_section=rag_section,
        memory_section=memory_section,
        strategy_focus=strategy["focus"],
        requirements=requirements,
        output_format=output_format,
    )


# ============================================================================
# JSON 解析工具
# ============================================================================

def parse_plan_response(response_text: str, output_format: str = "full") -> List[Dict[str, Any]]:
    """
    解析 LLM 返回的面试计划 JSON

    Args:
        response_text: LLM 返回的原始文本
        output_format: 期望的输出格式 - "full" 或 "simple"

    Returns:
        面试问题列表
    """
    # 尝试清理可能的 markdown 格式
    cleaned_text = clean_json_response(response_text)

    # 解析 JSON
    plan_data = json.loads(cleaned_text)

    # 根据格式提取问题列表
    if isinstance(plan_data, list):
        # simple 格式：直接返回数组
        interview_plan = plan_data
    else:
        # full 格式：从 questions 字段提取
        interview_plan = plan_data.get("questions", [])

    # 验证并补全数据结构
    for i, q in enumerate(interview_plan):
        if "id" not in q:
            q["id"] = i + 1
        if "topic" not in q:
            q["topic"] = "未知主题"
        if "content" not in q:
            q["content"] = q.get("question", "请描述一下相关经验")
        if "type" not in q:
            q["type"] = "tech"
        # 新增字段：来源和原因
        if "target_skill" not in q:
            q["target_skill"] = None
        if "sources" not in q:
            q["sources"] = []
        if "reason" not in q:
            q["reason"] = None
        if "fallback_reason" not in q:
            q["fallback_reason"] = None

    return interview_plan


# ============================================================================
# 核心规划函数
# ============================================================================

async def generate_interview_plan(
    resume: str,
    job_description: str,
    company_info: str,
    max_questions: int,
    api_config: Dict[str, Any],
    round_type: str = "tech_initial",
    round_index: int = 1,
    previous_profile: Optional[Dict] = None,
    previous_questions: Optional[List[str]] = None,
    output_format: str = "full",
    session_id: Optional[str] = None,
    save_to_db: bool = False,
    generate_hints: bool = False,
    weakness_report: Optional[Dict] = None,
    retrieval_context: Optional[Dict] = None,
    memory_context: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    生成面试计划（核心函数）

    Args:
        resume: 简历内容
        job_description: 岗位描述
        company_info: 公司信息
        max_questions: 最大问题数
        api_config: API 配置
        round_type: 轮次类型
        round_index: 当前轮次序号
        previous_profile: 上一轮的候选人画像（可选）
        previous_questions: 上一轮已问过的问题（可选）
        output_format: 输出格式 - "full" 包含 id/type，"simple" 只有 topic/content
        session_id: 会话 ID（用于保存到数据库）
        save_to_db: 是否保存到数据库
        generate_hints: 是否异步生成回答提示
        weakness_report: 短板报告（可选）
        retrieval_context: RAG 检索上下文（可选）
        memory_context: 长期记忆上下文（可选，来自 mem0）

    Returns:
        面试问题列表
    """
    response_text = ""
    try:
        # 构建 Prompt
        prompt = build_planner_prompt(
            resume=resume,
            job_description=job_description,
            company_info=company_info,
            max_questions=max_questions,
            round_type=round_type,
            round_index=round_index,
            previous_profile=previous_profile,
            previous_questions=previous_questions,
            output_format=output_format,
            weakness_report=weakness_report,
            retrieval_context=retrieval_context,
            memory_context=memory_context
        )

        prompt += "\n\n请直接输出纯 JSON，不要使用 markdown 代码块或其他额外文本。"

        output_model = PlanOutput if output_format == "full" else SimplePlanOutput
        structured_plan = await invoke_structured(
            prompt=prompt,
            output_model=output_model,
            api_config=api_config,
            channel="fast",
            max_retries=1,
        )

        interview_plan = [item.model_dump() for item in structured_plan.questions]
        if not interview_plan:
            logger.warning("[Planner] LLM 返回空计划，使用默认问题兜底。")
            interview_plan = _get_default_questions(max_questions, output_format)
        elif round_type == "tech_initial" and output_format == "full":
            interview_plan[0].update({
                "topic": DEFAULT_QUESTIONS[0]["topic"],
                "content": DEFAULT_QUESTIONS[0]["content"],
                "type": DEFAULT_QUESTIONS[0]["type"],
            })

        # 强制截断，确保数量符合要求（兜底逻辑）
        if len(interview_plan) > max_questions:
            logger.warning(f"[Planner] LLM 生成了 {len(interview_plan)} 道题，超过了要求的 {max_questions} 道，执行截断。")
            interview_plan = interview_plan[:max_questions]

        logger.info(f"[Planner] 成功生成 {len(interview_plan)} 个面试问题 (要求数量: {max_questions})")

        # 保存到数据库（如果需要）
        if save_to_db and session_id:
            try:
                from app.db.repositories.session.session_repo import SessionRepo
                service = SessionRepo()
                await service.save_interview_plan(session_id, interview_plan)
                logger.info(f"[Planner] 面试计划已保存到数据库: {session_id}")

                # 异步生成回答提示（如果需要）
                if generate_hints:
                    from ai.runtime.background_tasks import create_background_task
                    create_background_task(_generate_hints_async(
                        session_id=session_id,
                        interview_plan=interview_plan,
                        resume=resume,
                        job_desc=job_description,
                        api_config=api_config
                    ), name=f"hint-generation:{session_id}")
                    logger.info(f"[Planner] 已触发后台提示生成任务: {session_id}")

            except Exception as e:
                logger.error(f"[Planner] 保存面试计划失败: {e}")

        return interview_plan

    except Exception as e:
        logger.error(f"[Planner] 生成面试计划失败: {e}")
        return _get_default_questions(max_questions, output_format)


def _get_default_questions(max_questions: int, output_format: str = "full") -> List[Dict[str, Any]]:
    """
    获取默认问题（兜底方案）
    """
    questions = DEFAULT_QUESTIONS[:max_questions]

    if output_format == "simple":
        # 转换为简单格式
        return [{"topic": q["topic"], "content": q["content"]} for q in questions]

    return questions


# ============================================================================
# 回答提示生成（后台任务）
# ============================================================================

async def _generate_hints_async(
    session_id: str,
    interview_plan: list,
    resume: str,
    job_desc: str,
    api_config: Optional[Dict[str, Any]] = None
):
    """
    异步生成回答提示（后台任务）

    使用 fast 模型为每道题目生成回答提示，完成后更新数据库
    """
    try:
        logger.info(f"[HintGenerator] 开始为会话 {session_id} 生成回答提示")

        # 构建所有问题的提示生成 prompt
        questions_text = "\n".join([
            f"{i+1}. [{q.get('topic', '')}] {q.get('content', '')}"
            for i, q in enumerate(interview_plan)
        ])

        from ai.prompts.interview import build_hints_prompt

        prompt = build_hints_prompt(questions_text)

        hints_output = await invoke_structured(
            prompt=prompt,
            output_model=HintOutput,
            api_config=api_config,
            channel="fast",
            max_retries=2,
        )
        hints_list = hints_output.hints

        # 将提示合并到 interview_plan
        for i, q in enumerate(interview_plan):
            if i < len(hints_list):
                q["hint"] = hints_list[i]
            else:
                q["hint"] = "可以结合自身经验，从实际案例出发进行回答。"

        # 更新数据库
        from app.db.repositories.session.session_repo import SessionRepo
        service = SessionRepo()
        await service.save_interview_plan(session_id, interview_plan)

        logger.info(f"[HintGenerator] 会话 {session_id} 的回答提示已生成并保存")

    except Exception as e:
        logger.error(f"[HintGenerator] 生成回答提示失败: {str(e)}", exc_info=True)
