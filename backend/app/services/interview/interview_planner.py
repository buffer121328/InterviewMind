"""
面试规划统一模块
将 voice_interview.py 和 graph.py 中的规划逻辑抽离复用
"""

import json
import logging
from typing import List, Dict, Any, Optional

from app.schemas.llm_outputs import PlanOutput, SimplePlanOutput, HintOutput
from app.services.llm_utils import invoke_structured, clean_json_response

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
    output_format: str = "full",  # "full" 或 "simple"
    weakness_report: Optional[Dict] = None,
    retrieval_context: Optional[Dict] = None,
    memory_context: Optional[str] = None
) -> str:
    """
    构建面试规划 Prompt

    上下文传递规范化 —— 7 项固定输入（按文档定义）：
    1. job_description       — 当前岗位 JD
    2. resume                — 当前候选人简历快照
    3. previous_questions    — 上一轮问题列表（避免重复出题）
    4. previous_profile      — 上一轮候选人画像（表现摘要）
    5. weakness_report       — 上一轮短板报告
    6. previous_profile      — 候选人分层画像（累积，同上字段）
    7. memory_context        — 长期记忆上下文
    
    Args:
        resume: 简历内容
        job_description: 岗位描述
        company_info: 公司信息
        max_questions: 最大问题数
        round_type: 轮次类型 (tech_initial, tech_deep, hr_comprehensive, voice_default)
        round_index: 当前轮次序号
        previous_profile: 上一轮的候选人画像（可选）
        previous_questions: 上一轮已问过的问题（可选，用于避免重复）
        output_format: 输出格式 - "full" 包含 id/type，"simple" 只有 topic/content
        weakness_report: 短板报告（可选）
        retrieval_context: RAG 检索上下文（可选）
        memory_context: 长期记忆上下文（可选，来自 mem0）
        
    Returns:
        构建好的 Prompt 字符串
    """
    # 获取轮次策略
    strategy = ROUND_STRATEGIES.get(round_type, ROUND_STRATEGIES["tech_initial"])
    
    # 如果是深度轮次且有上一轮画像，添加参考信息
    requirements = strategy["requirements"]
    if round_type == "tech_deep" and previous_profile:
        assessment = previous_profile.get("overall_assessment", "")[:200]
        if assessment:
            requirements = requirements.replace(
                "从简历已有内容延伸",
                f"从简历已有内容延伸。上一轮评估供参考：{assessment}"
            )
    
    # 构建公司信息部分
    company_section = f"\n    【公司信息】：\n    {company_info}\n" if company_info else ""
    
    # 构建上一轮问题部分（避免重复）
    previous_questions_section = ""
    if previous_questions:
        questions_text = "\n".join([f"    - {q}" for q in previous_questions])
        previous_questions_section = f"""
    【上一轮已问过的问题（请勿重复）】：
{questions_text}
"""

    # 构建短板地图上下文（多轮面试增强）
    weakness_section = ""
    if weakness_report:
        weakness_categories = weakness_report.get("weakness_categories", [])
        if weakness_categories:
            weakness_text = "\n".join([
                f"    - [{cat.get('severity', 'medium')}] {cat.get('category', '')}: {cat.get('description', '')}"
                for cat in weakness_categories[:4]
            ])
            weakness_section = f"""
    【上一轮面试短板（请重点追问）】：
{weakness_text}
    请在本轮面试中适当增加对这些薄弱领域的追问，但不要完全重复上一轮的题目。
"""
    
    # 构建 RAG 检索上下文
    rag_section = ""
    if retrieval_context:
        # 优先使用新的 rag_evidences（带来源和分数）
        rag_evidences = retrieval_context.get("rag_evidences", [])
        if rag_evidences:
            evidence_text = "\n".join([
                f"    - [{ev.get('source_type', '')}] {ev.get('evidence', '')[:120]} (score: {ev.get('retrieval_score', 0):.2f})"
                for ev in rag_evidences[:6]
            ])
            rag_section = f"""
    【检索证据（面试题生成依据）】：
{evidence_text}
    请基于以上证据生成面试题。每道题应至少引用一个证据来源。
"""
        else:
            # 兼容旧格式
            bank_questions = retrieval_context.get("bank_questions", [])
            if bank_questions:
                bank_text = "\n".join([
                    f"    - [{q.get('difficulty', 'medium')}] {q.get('question_text', '')}"
                    for q in bank_questions[:3]
                ])
                rag_section = f"""
    【题库参考题目（可作为出题灵感）】：
{bank_text}
"""

    memory_section = ""
    if memory_context:
        memory_section = f"""
    【候选人长期记忆】：
{memory_context}
    请结合这些长期记忆调整题目侧重点，但不要直接泄露记忆来源。
"""
    
    # 根据输出格式选择 JSON 结构
    if output_format == "simple":
        json_format = """```json
[
  {"topic": "自我介绍", "content": "请做一个简短的自我介绍"},
  {"topic": "项目经验", "content": "你在XX项目中遇到的最大挑战是什么？"}
]
```

只返回 JSON 数组，不要有其他内容。"""
    else:
        json_format = """{
        "questions": [
            {
                "id": 1,
                "topic": "考察主题",
                "content": "具体问题内容",
                "type": "题目类型(intro/tech/behavior/system_design)",
                "target_skill": "目标技能（可选）",
                "sources": [
                    {
                        "source_type": "candidate_material",
                        "source_id": "123",
                        "evidence": "证据摘要"
                    }
                ],
                "reason": "为什么问这道题（引用证据）",
                "fallback_reason": null
            }
        ]
    }
    
    说明：
    - sources: 列出生成这道题所依据的证据来源。如果没有明确证据，留空数组。
    - reason: 解释为什么问这道题，必须引用证据。
    - fallback_reason: 如果因为证据不足而回退到默认出题，填写原因；否则为 null。"""
    
    # 构建完整 Prompt
    prompt = f"""你是一位资深面试官。这是第 {round_index} 轮面试（类型：{round_type}）。
    你的任务是：根据以下信息，设计**不多不少，正好 {max_questions} 道**面试题目。
    
    【岗位描述】：
    {job_description or "未提供"}
    {company_section}
    【候选人简历】：
    {resume or "未提供"}
    {previous_questions_section}
    {weakness_section}
    {rag_section}
    {memory_section}
    【本轮面试侧重点】：{strategy['focus']}
    
    要求：
    {requirements}
    【重要】：你只能生成 {max_questions} 道题目。
    
    【问题内容规范】：
    1. 每个问题必须是直接的、具体的问题，不要包含元语言
    2. 保持问题的自然性和专业性，就像真实面试官会问的问题
    
    请严格按照以下 JSON 结构输出数组，确保包含所有字段。
    不要包含 markdown 格式（如 ```json ... ```），只输出纯 JSON 字符串，使用英文字符，禁止使用emoji。
    {json_format}
    """
    
    return prompt


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
            channel="smart",
            max_retries=2,
        )

        interview_plan = [item.model_dump() for item in structured_plan.questions]
        if not interview_plan:
            logger.warning("[Planner] LLM 返回空计划，使用默认问题兜底。")
            interview_plan = _get_default_questions(max_questions, output_format)
        
        # 强制截断，确保数量符合要求（兜底逻辑）
        if len(interview_plan) > max_questions:
            logger.warning(f"[Planner] LLM 生成了 {len(interview_plan)} 道题，超过了要求的 {max_questions} 道，执行截断。")
            interview_plan = interview_plan[:max_questions]
        
        logger.info(f"[Planner] 成功生成 {len(interview_plan)} 个面试问题 (要求数量: {max_questions})")
        
        # 保存到数据库（如果需要）
        if save_to_db and session_id:
            try:
                from app.repositories.session.session_repo import SessionRepo
                service = SessionRepo()
                await service.save_interview_plan(session_id, interview_plan)
                logger.info(f"[Planner] 面试计划已保存到数据库: {session_id}")
                
                # 异步生成回答提示（如果需要）
                if generate_hints:
                    from app.services.background_tasks import create_background_task
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
        
        prompt = f"""你是一位面试辅导专家。以下是面试官将要问候选人的问题列表。
请为每道题目生成简洁的回答提示，帮助候选人组织回答思路。

【面试问题列表】：
{questions_text}

请为每道题生成回答提示，格式要求：
1. 每道题的提示控制在50-100字
2. 提示应包含：回答的角度、需要涵盖的要点、可以举例的方向
3. 不要直接给出答案，而是引导思路

请严格按照以下 JSON 格式输出，标点符号使用英文格式，不要包含 markdown 格式，不要有emoji表情：
{{
    "hints": [
        "第1题的回答提示...",
        "第2题的回答提示...",
        ...
    ]
}}
"""

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
        from app.repositories.session.session_repo import SessionRepo
        service = SessionRepo()
        await service.save_interview_plan(session_id, interview_plan)
        
        logger.info(f"[HintGenerator] 会话 {session_id} 的回答提示已生成并保存")
        
    except Exception as e:
        logger.error(f"[HintGenerator] 生成回答提示失败: {str(e)}", exc_info=True)
