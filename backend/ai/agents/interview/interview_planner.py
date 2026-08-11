"""
面试规划统一模块
已知超限：职责单一（面试规划），暂不拆分。
将 voice_interview.py 和 graph.py 中的规划逻辑抽离复用
"""

import asyncio
import json
import logging
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

from ai.llm.llm_utils import clean_json_response, invoke_structured
from ai.runtime.context_assembler import ContextAssembler, ContextSource
from ai.runtime.deadlines import TaskDeadline
from app.config import get_settings
from app.domain.interview_rounds import (
    MAX_QUESTIONS,
    SYSTEM_FALLBACK_QUESTION_SOURCE_TYPE,
)
from app.schemas.llm_outputs import HintOutput, PlanOutput, SimplePlanOutput

from .answer_points import ensure_question_answer_points
from .context_compaction import PlannerContextBundle, assemble_planner_context

logger = logging.getLogger(__name__)

# 面试启动属于用户阻塞链路；模型池自身可能有多通道和重试，因此使用独立总预算，
# 超时后立即使用本地题目兜底，避免单次启动累计等待数分钟。


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

ROUND_DEFAULT_QUESTIONS: Dict[str, List[Dict[str, Any]]] = {
    "tech_initial": [
        {"topic": "自我介绍", "content": "请做一个简短的自我介绍，包括你的教育背景和工作经历。", "type": "intro"},
        {"topic": "岗位理解", "content": "你如何理解这个岗位的核心职责，你认为自己最匹配的能力是什么？", "type": "behavior"},
        {"topic": "项目概述", "content": "请选择一个最能代表你能力的项目，说明目标、规模和最终结果。", "type": "tech"},
        {"topic": "个人贡献", "content": "在这个项目中你具体负责哪些部分，哪些关键结果可以归因于你的工作？", "type": "behavior"},
        {"topic": "技术选型", "content": "项目的核心技术栈是如何选择的，当时比较过哪些替代方案？", "type": "tech"},
        {"topic": "基础原理", "content": "请解释一个你在项目中频繁使用的核心技术原理，以及它解决了什么问题。", "type": "tech"},
        {"topic": "数据建模", "content": "你通常如何根据业务需求设计数据模型并控制后续变更成本？", "type": "tech"},
        {"topic": "接口设计", "content": "设计一个业务接口时，你会如何考虑参数、错误处理、幂等和兼容性？", "type": "tech"},
        {"topic": "并发处理", "content": "请举例说明你处理过的并发或竞态问题，以及最终采用的方案。", "type": "tech"},
        {"topic": "故障排查", "content": "线上出现无法稳定复现的问题时，你会按照什么顺序定位根因？", "type": "tech"},
        {"topic": "测试策略", "content": "你如何划分单元测试、集成测试和端到端测试的边界？", "type": "tech"},
        {"topic": "性能优化", "content": "请介绍一次有数据依据的性能优化经历，优化前后指标有什么变化？", "type": "tech"},
        {"topic": "安全意识", "content": "你在开发接口或处理用户数据时会重点防范哪些安全风险？", "type": "tech"},
        {"topic": "发布流程", "content": "你参与过的代码发布流程是怎样的，如何降低上线风险？", "type": "tech"},
        {"topic": "可观测性", "content": "你会为一个新服务设计哪些日志、指标和告警？", "type": "tech"},
        {"topic": "学习能力", "content": "最近一年你主动学习并应用的一项技术是什么，应用效果如何？", "type": "behavior"},
        {"topic": "团队协作", "content": "请描述一次你与团队成员意见不一致的经历，你是如何推进决策的？", "type": "behavior"},
        {"topic": "失败复盘", "content": "请介绍一次结果未达预期的任务，以及你从中调整了什么。", "type": "behavior"},
        {"topic": "优先级管理", "content": "多个紧急任务同时出现时，你如何判断优先级并同步风险？", "type": "behavior"},
        {"topic": "岗位匹配", "content": "如果入职后前三个月要交付一个关键结果，你会如何开展工作？", "type": "behavior"},
    ],
    "tech_deep": [
        {"topic": "架构全景", "content": "请选择上一轮提到的一个核心项目，画出主要组件和数据流，并说明最关键的架构约束。", "type": "system_design"},
        {"topic": "技术难点", "content": "这个项目中最难解决的技术问题是什么，你用哪些证据确认真正的根因？", "type": "tech"},
        {"topic": "方案权衡", "content": "针对该难点你比较过哪些方案，最终方案在复杂度、成本和风险上做了什么取舍？", "type": "tech"},
        {"topic": "性能瓶颈", "content": "如果该系统响应变慢，你会用哪些指标和工具定位 CPU、内存、网络或存储瓶颈？", "type": "tech"},
        {"topic": "并发正确性", "content": "系统中的并发写入如何避免重复处理、竞态条件和数据覆盖？", "type": "tech"},
        {"topic": "数据一致性", "content": "跨服务或跨数据源更新时，你如何选择事务、补偿或最终一致性方案？", "type": "system_design"},
        {"topic": "缓存设计", "content": "请说明项目中的缓存键、过期、淘汰和失效策略，以及如何处理缓存一致性。", "type": "tech"},
        {"topic": "数据库优化", "content": "面对一条慢查询，你会如何分析执行计划、索引设计和数据分布？", "type": "tech"},
        {"topic": "异步任务", "content": "如果使用消息队列处理关键任务，你如何保证幂等、重试、顺序和死信恢复？", "type": "system_design"},
        {"topic": "故障恢复", "content": "请列出该系统最重要的三个故障模式，并说明检测、降级和恢复方案。", "type": "system_design"},
        {"topic": "可观测性", "content": "为了定位一次跨服务故障，你会如何关联日志、指标和分布式追踪？", "type": "tech"},
        {"topic": "安全边界", "content": "该项目的身份认证、权限控制和敏感数据保护分别在哪一层实现？", "type": "tech"},
        {"topic": "测试深度", "content": "项目中哪些高风险路径必须做集成或故障注入测试，为什么？", "type": "tech"},
        {"topic": "发布回滚", "content": "数据库结构和应用版本同时变化时，你如何设计灰度发布与安全回滚？", "type": "system_design"},
        {"topic": "容量扩展", "content": "如果流量和数据量增长十倍，当前架构最先失效的部分是什么，你会如何演进？", "type": "system_design"},
        {"topic": "系统设计", "content": "请基于目标岗位设计一个中等规模服务，说明接口、存储、缓存和异步处理边界。", "type": "system_design"},
        {"topic": "工程质量", "content": "项目中最值得重构的一段设计是什么，技术债是如何形成并被控制的？", "type": "tech"},
        {"topic": "事故复盘", "content": "请复盘一次你亲自参与的线上事故，说明时间线、决策点和防复发措施。", "type": "behavior"},
        {"topic": "贡献验证", "content": "如果让项目同事验证你的核心贡献，他们会用哪些代码、指标或交付结果来证明？", "type": "behavior"},
        {"topic": "重新设计", "content": "如果现在重新实现这个项目，你会保留什么、推翻什么，并说明依据。", "type": "system_design"},
    ],
    "hr_comprehensive": [
        {"topic": "求职动机", "content": "你为什么考虑这个岗位和公司，目前最看重的机会是什么？", "type": "behavior"},
        {"topic": "职业规划", "content": "你未来三年的职业目标是什么，这个岗位如何帮助你实现目标？", "type": "behavior"},
        {"topic": "优势定位", "content": "与同阶段候选人相比，你最突出的优势是什么，请给出具体例子。", "type": "behavior"},
        {"topic": "成长短板", "content": "你当前最需要提升的一项能力是什么，已经采取了哪些行动？", "type": "behavior"},
        {"topic": "离职原因", "content": "你离开上一段经历或考虑新机会的主要原因是什么？", "type": "behavior"},
        {"topic": "压力应对", "content": "请介绍一次高压且时间紧迫的任务，你如何保证结果和团队状态？", "type": "behavior"},
        {"topic": "冲突处理", "content": "当你与直属负责人观点不一致时，你通常如何沟通和执行？", "type": "behavior"},
        {"topic": "跨团队协作", "content": "请举例说明你如何推动一个依赖多个团队的事项按期完成。", "type": "behavior"},
        {"topic": "影响力", "content": "在没有正式管理权限时，你如何说服他人支持你的方案？", "type": "behavior"},
        {"topic": "反馈处理", "content": "你收到过最有价值的一次负面反馈是什么，之后做了哪些改变？", "type": "behavior"},
        {"topic": "失败经历", "content": "请介绍一次重要失败，你承担了什么责任并如何修正？", "type": "behavior"},
        {"topic": "价值观", "content": "在效率、质量和诚信发生冲突时，你会如何做决定？", "type": "behavior"},
        {"topic": "客户意识", "content": "请举例说明你如何识别并解决用户或内部客户的真实需求。", "type": "behavior"},
        {"topic": "主动性", "content": "请介绍一件没有人明确要求、但你主动推动并产生价值的事情。", "type": "behavior"},
        {"topic": "适应变化", "content": "需求或组织方向突然变化时，你如何调整计划并稳定交付？", "type": "behavior"},
        {"topic": "领导力", "content": "请描述一次你带领他人完成困难目标的经历。", "type": "behavior"},
        {"topic": "工作方式", "content": "你理想的管理方式和团队协作氛围是什么？", "type": "behavior"},
        {"topic": "薪资期望", "content": "你对薪资和整体回报有什么期望，主要依据是什么？", "type": "behavior"},
        {"topic": "入职计划", "content": "如果顺利入职，你计划如何度过前九十天？", "type": "behavior"},
        {"topic": "反向提问", "content": "为了判断岗位是否适合你，你最希望进一步了解哪些信息？", "type": "behavior"},
    ],
}
for _catalog in ROUND_DEFAULT_QUESTIONS.values():
    for _index, _question in enumerate(_catalog, start=1):
        _question["id"] = _index
ROUND_DEFAULT_QUESTIONS["voice_default"] = ROUND_DEFAULT_QUESTIONS["tech_initial"]

# 保留原常量名供评测和外部导入使用；调用方必须通过 `_get_default_questions`
# 获取独立副本，避免在运行时修改共享目录。
DEFAULT_QUESTIONS = ROUND_DEFAULT_QUESTIONS["tech_initial"]


# ============================================================================
# Prompt 构建器
# ============================================================================

def _build_planner_prompt_bundle(
    *,
    resume: str,
    job_description: str,
    company_info: str,
    max_questions: int,
    round_type: str,
    round_index: int,
    previous_profile: Optional[Dict],
    previous_questions: Optional[List[str]],
    output_format: str,
    weakness_report: Optional[Dict],
    retrieval_context: Optional[Dict],
    memory_context: Optional[str],
    previous_summary: Optional[str],
    owner_id: str,
    cache_scope: str,
) -> tuple[str, PlannerContextBundle]:
    """构建规划器提示词打包相关后端逻辑。"""
    from ai.prompts.interview import (
        build_planner_prompt as build_central_planner_prompt,
    )

    strategy = ROUND_STRATEGIES.get(round_type, ROUND_STRATEGIES["tech_initial"])
    bundle = assemble_planner_context(
        owner_id=owner_id,
        cache_scope=cache_scope,
        resume=resume,
        job_description=job_description,
        company_info=company_info,
        round_index=round_index,
        round_type=round_type,
        max_questions=max_questions,
        strategy_focus=strategy["focus"],
        requirements=strategy["requirements"],
        previous_questions=previous_questions,
        previous_profile=previous_profile,
        weakness_report=weakness_report,
        previous_summary=previous_summary,
        retrieval_context=retrieval_context,
        memory_context=memory_context,
    )
    prompt = build_central_planner_prompt(
        round_index=round_index,
        round_type=round_type,
        max_questions=max_questions,
        strategy_focus=strategy["focus"],
        requirements=strategy["requirements"],
        output_format=output_format,
        planning_context=bundle.assembled.model_context,
    )
    return prompt, bundle


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
    previous_summary: Optional[str] = None,
    owner_id: str = "",
    cache_scope: str = "",
) -> str:
    """构建规划器提示词相关后端逻辑。"""
    prompt, _bundle = _build_planner_prompt_bundle(
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
        memory_context=memory_context,
        previous_summary=previous_summary,
        owner_id=owner_id,
        cache_scope=cache_scope,
    )
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
    memory_context: Optional[str] = None,
    previous_summary: Optional[str] = None,
    owner_id: str = "",
    cache_scope: str = "",
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
        previous_summary: 上一轮候选人可见摘要（可选）
        owner_id: 缓存 owner；生产调用应传当前用户 ID
        cache_scope: 同一会话系列内复用事实缓存的稳定作用域

    Returns:
        面试问题列表
    """
    try:
        prompt, context_bundle = _build_planner_prompt_bundle(
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
            memory_context=memory_context,
            previous_summary=previous_summary,
            owner_id=owner_id,
            cache_scope=cache_scope,
        )
        prompt += "\n\n请直接输出纯 JSON，不要使用 markdown 代码块或其他额外文本。"

        output_model = PlanOutput if output_format == "full" else SimplePlanOutput
        deadline = TaskDeadline(float(get_settings().interview_plan_timeout_seconds))
        structured_plan = await asyncio.wait_for(
            invoke_structured(
                prompt=prompt,
                output_model=output_model,
                api_config=api_config,
                channel="fast",
                max_retries=1,
                deadline=deadline,
                call_metadata=context_bundle.assembled.model_event_fields(),
            ),
            timeout=max(0.001, deadline.remaining()),
        )

        interview_plan = [item.model_dump() for item in structured_plan.questions]
        if not interview_plan:
            logger.warning("[Planner] LLM 返回空计划，使用当前轮次的默认问题兜底。")
        elif round_type == "tech_initial" and output_format == "full":
            canonical_intro = ensure_question_answer_points(DEFAULT_QUESTIONS[0])
            interview_plan[0].update({
                "topic": canonical_intro["topic"],
                "content": canonical_intro["content"],
                "type": canonical_intro["type"],
                "answer_points": canonical_intro["answer_points"],
                "source_type": SYSTEM_FALLBACK_QUESTION_SOURCE_TYPE,
                "fallback_reason": "canonical_intro",
            })

        interview_plan = _ensure_plan_question_count(
            interview_plan,
            max_questions=max_questions,
            output_format=output_format,
            round_type=round_type,
            previous_questions=previous_questions,
        )

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
                        api_config=api_config
                    ), name=f"hint-generation:{session_id}")
                    logger.info(f"[Planner] 已触发后台提示生成任务: {session_id}")

            except Exception as e:
                logger.error(f"[Planner] 保存面试计划失败: {e}")

        return [ensure_question_answer_points(item) for item in interview_plan]

    except Exception as exc:
        logger.error(
            "[Planner] 生成面试计划失败，使用本地问题兜底: error_type=%s",
            type(exc).__name__,
        )
        return _get_default_questions(
            max_questions,
            output_format,
            round_type=round_type,
            previous_questions=previous_questions,
            include_provenance=True,
        )


def _normalize_question_key(content: str) -> str:
    """规范化题目键相关后端逻辑。"""
    normalized = " ".join(str(content or "").casefold().split())
    return "".join(char for char in normalized if char not in "，。！？；：,.!?;:、")


def _is_near_duplicate(content: str, existing: List[str], *, threshold: float = 0.86) -> bool:
    """处理面试规划器相关后端逻辑。"""
    key = _normalize_question_key(content)
    if not key:
        return True
    for prior in existing:
        prior_key = _normalize_question_key(prior)
        if not prior_key:
            continue
        if key == prior_key:
            return True
        if SequenceMatcher(None, key, prior_key).ratio() >= threshold:
            return True
    return False


def _get_default_questions(
    max_questions: int,
    output_format: str = "full",
    *,
    round_type: str = "tech_initial",
    previous_questions: Optional[List[str]] = None,
    include_provenance: bool = False,
) -> List[Dict[str, Any]]:
    """获取默认题目相关后端逻辑。"""
    requested_count = min(max(int(max_questions or 0), 0), MAX_QUESTIONS)
    if requested_count == 0:
        return []

    catalog = ROUND_DEFAULT_QUESTIONS.get(round_type, DEFAULT_QUESTIONS)
    existing_questions = [str(item) for item in (previous_questions or []) if str(item).strip()]
    selected: List[Dict[str, Any]] = []
    seen_exact = {_normalize_question_key(item) for item in existing_questions}
    for raw in catalog:
        content = str(raw.get("content") or "").strip()
        key = _normalize_question_key(content)
        if not key or key in seen_exact or _is_near_duplicate(content, existing_questions):
            continue
        seen_exact.add(key)
        existing_questions.append(content)
        selected.append(dict(raw))
        if len(selected) >= requested_count:
            break

    supplement_topic = {
        "tech_deep": "补充技术深挖",
        "hr_comprehensive": "补充综合评估",
    }.get(round_type, "补充能力评估")
    supplement_type = "tech" if round_type == "tech_deep" else "behavior"
    supplement_attempt = 0
    while len(selected) < requested_count:
        supplement_attempt += 1
        ordinal = len(selected) + 1
        content = (
            f"{supplement_topic}第 {ordinal} 题（角度 {supplement_attempt}）："
            "请选择一个尚未讨论的具体案例，说明当时的约束、你的判断、采取的行动和可验证结果。"
        )
        key = _normalize_question_key(content)
        # 补充题使用独立 attempt 避免历史中已有同序号模板时循环无法推进。
        if key not in seen_exact:
            seen_exact.add(key)
            existing_questions.append(content)
            selected.append({
                "topic": supplement_topic,
                "content": content,
                "type": supplement_type,
            })

    if output_format == "simple":
        questions = [
            {"topic": item["topic"], "content": item["content"]}
            for item in selected
        ]
    else:
        questions = [
            {**item, "id": index}
            for index, item in enumerate(selected, start=1)
        ]

    if include_provenance:
        for item in questions:
            item["source_type"] = SYSTEM_FALLBACK_QUESTION_SOURCE_TYPE
            item["fallback_reason"] = "local_default_question"
    return [ensure_question_answer_points(item) for item in questions]


def _ensure_plan_question_count(
    interview_plan: List[Dict[str, Any]],
    *,
    max_questions: int,
    output_format: str,
    round_type: str,
    previous_questions: Optional[List[str]],
) -> List[Dict[str, Any]]:
    """确保计划题目相关后端逻辑。"""
    requested_count = min(max(int(max_questions or 0), 0), MAX_QUESTIONS)
    existing_questions = [str(item) for item in (previous_questions or []) if str(item).strip()]
    normalized: List[Dict[str, Any]] = []
    seen_exact = {_normalize_question_key(item) for item in existing_questions}

    for raw in interview_plan:
        content = str(raw.get("content") or "").strip()
        key = _normalize_question_key(content)
        if not key or key in seen_exact or _is_near_duplicate(content, existing_questions):
            continue
        seen_exact.add(key)
        existing_questions.append(content)
        normalized.append(dict(raw))
        if len(normalized) >= requested_count:
            break

    if len(normalized) < requested_count:
        fallback = _get_default_questions(
            requested_count,
            output_format,
            round_type=round_type,
            previous_questions=[
                *(previous_questions or []),
                *(str(item.get("content") or "") for item in normalized),
            ],
            include_provenance=True,
        )
        for raw in fallback:
            content = str(raw.get("content") or "").strip()
            key = _normalize_question_key(content)
            if not key or key in seen_exact:
                continue
            seen_exact.add(key)
            existing_questions.append(content)
            normalized.append(dict(raw))
            if len(normalized) >= requested_count:
                break

    if output_format == "full":
        for index, item in enumerate(normalized, start=1):
            item["id"] = index
    return [ensure_question_answer_points(item) for item in normalized]


# ============================================================================
# 回答提示生成（后台任务）
# ============================================================================

async def _generate_hints_async(
    session_id: str,
    interview_plan: list,
    api_config: Optional[Dict[str, Any]] = None
):
    """
    异步生成回答提示（后台任务）

    使用 fast 模型为每道题目生成回答提示，完成后更新数据库
    """
    try:
        logger.info(f"[HintGenerator] 开始为会话 {session_id} 生成回答提示")

        assembled = ContextAssembler(
            agent_name="interview_hints",
            total_model_chars=5000,
            source_budgets={"question_plan": 5000},
            cache_version="2026-07-29.phase6.hints.v1",
        ).assemble([
            ContextSource(
                name="question_plan",
                content=[
                    {
                        "index": index + 1,
                        "topic": question.get("topic", ""),
                        "content": question.get("content", ""),
                    }
                    for index, question in enumerate(interview_plan)
                    if isinstance(question, dict)
                ],
                trusted=True,
                required=True,
                max_chars=5000,
                truncation_strategy="head_tail",
            )
        ])

        from ai.prompts.interview import build_hints_prompt

        prompt = build_hints_prompt(assembled.model_context)

        hints_output = await invoke_structured(
            prompt=prompt,
            output_model=HintOutput,
            api_config=api_config,
            channel="fast",
            max_retries=2,
            deadline=TaskDeadline(float(get_settings().interview_plan_timeout_seconds)),
            call_metadata={
                **assembled.model_event_fields(),
                "stage": "interview_hint_generation",
            },
        )
        hints_list = hints_output.hints

        # 将提示合并到 interview_plan
        for i, q in enumerate(interview_plan):
            if i < len(hints_list):
                q["hint"] = hints_list[i]
                q["answer_points"] = ensure_question_answer_points({"hint": hints_list[i]})["answer_points"]
            else:
                q["hint"] = "可以结合自身经验，从实际案例出发进行回答。"
                q["answer_points"] = ensure_question_answer_points(q)["answer_points"]

        # 更新数据库
        from app.db.repositories.session.session_repo import SessionRepo
        service = SessionRepo()
        await service.save_interview_plan(session_id, interview_plan)

        logger.info(f"[HintGenerator] 会话 {session_id} 的回答提示已生成并保存")

    except Exception as e:
        logger.error(f"[HintGenerator] 生成回答提示失败: {str(e)}", exc_info=True)
