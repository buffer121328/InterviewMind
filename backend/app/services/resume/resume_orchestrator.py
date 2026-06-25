"""
简历优化 6 阶段流水线编排器

替代原有的 8 节点"圆桌会议"式架构（resume_optimizer_graph.py），
使用固定 DAG 拓扑的 Pipeline 范式：

  阶段1: JD分析        → 匹配分、关键词、优先改写点
  阶段2: 素材选择       → 候选人素材池、证据来源
  阶段3: 定制改写       → 每条改写输出标准 ChangeItem
  阶段4: 简历组装       → 完整 Markdown 简历
  阶段5: 事实核验       → 风险标记、夸大检测、失真检测
  阶段6: 用户确认       → 高风险改写确认、最终保存、审计日志

设计原则：
- 每阶段是独立的结构化 LLM 调用，不涉及 Agent 自主决策
- 每阶段输出固定 Schema，产物可独立审查、可回溯
- Token 成本固定 N 次 LLM 调用，不可控循环
"""

import json
import logging
from typing import Dict, Any, List, Optional, TypedDict
from dataclasses import dataclass, field

from app.schemas.llm_outputs import ChangeItem, MatchAnalysisOutput, ContentSuggestionsOutput
from app.services.llm_utils import invoke_structured

logger = logging.getLogger(__name__)


# ============================================================================
# Pipeline 状态定义
# ============================================================================

@dataclass
class PipelineState:
    """流水线状态 — 在各阶段间传递"""
    # 输入
    resume_content: str
    job_description: str
    user_id: str = "default_user"
    api_config: Optional[dict] = None
    
    # 阶段产出
    jd_analysis: Optional[dict] = None           # 阶段1
    material_pool: Optional[dict] = None          # 阶段2
    change_items: List[dict] = field(default_factory=list)  # 阶段3
    assembled_resume: str = ""                     # 阶段4
    fact_check_result: Optional[dict] = None       # 阶段5
    confirmation_items: List[dict] = field(default_factory=list)  # 阶段6
    
    # 元数据
    errors: List[str] = field(default_factory=list)


# ============================================================================
# 6 阶段流水线编排
# ============================================================================

async def run_pipeline(
    resume_content: str,
    job_description: str,
    user_id: str = "default_user",
    api_config: Optional[dict] = None,
    session_ids: List[str] = [],
    include_profile: bool = False,
) -> Dict[str, Any]:
    """
    执行 6 阶段简历优化流水线。
    
    Args:
        resume_content: 原始简历内容
        job_description: 目标岗位 JD
        user_id: 用户 ID
        api_config: API 配置
        session_ids: 关联的面试 session
        include_profile: 是否包含综合能力画像
        
    Returns:
        完整的流水线产出，包含所有阶段的产物
    """
    state = PipelineState(
        resume_content=resume_content,
        job_description=job_description,
        user_id=user_id,
        api_config=api_config,
    )
    
    logger.info(f"[ResumePipeline] 开始 6 阶段流水线 (user_id={user_id})")
    
    # 阶段1: JD 分析
    state = await stage1_jd_analysis(state)
    
    # 阶段2: 素材选择
    state = await stage2_material_selection(state, session_ids, include_profile)
    
    # 阶段3: 定制改写
    state = await stage3_custom_rewrite(state)
    
    # 阶段4: 简历组装
    state = await stage4_assemble(state)
    
    # 阶段5: 事实核验
    state = await stage5_fact_check(state)
    
    # 阶段6: 用户确认准备
    state = await stage6_confirmation_prep(state)
    
    logger.info(f"[ResumePipeline] 流水线完成, {len(state.change_items)} 条改写, {len(state.confirmation_items)} 条需确认")
    
    return {
        "jd_analysis": state.jd_analysis,
        "material_pool": state.material_pool,
        "change_items": state.change_items,
        "assembled_resume": state.assembled_resume,
        "fact_check": state.fact_check_result,
        "confirmation_items": state.confirmation_items,
        "errors": state.errors,
        "overall_confidence": _calc_confidence(state.change_items),
        "requires_user_review": len(state.confirmation_items) > 0,
    }


# ============================================================================
# 阶段1: JD 分析
# ============================================================================

async def stage1_jd_analysis(state: PipelineState) -> PipelineState:
    """
    阶段1: JD 分析
    
    输出：
    - 匹配分 (0-100)
    - 命中关键词列表
    - 缺失关键词列表
    - 优先改写点（按重要性排序）
    - 适合强调的项目和经历
    """
    if not state.job_description:
        state.jd_analysis = {"match_score": 0, "note": "无 JD 提供"}
        return state
    
    prompt = f"""你是一位专业的「JD匹配分析师」。请分析以下简历与职位描述的匹配情况。

【职位描述】：
{state.job_description}

【简历内容】：
{state.resume_content[:2000]}

请完成以下分析，输出 JSON：
{{
    "jd_keywords": ["关键词1", "关键词2", ...],
    "matched_keywords": ["匹配的关键词1", ...],
    "missing_keywords": ["缺失的关键词1", ...],
    "bonus_items": ["加分项1", ...],
    "match_score": 75,
    "priority_rewrite_points": [
        {{"area": "工作经历", "action": "添加量化数据", "priority": 1}},
        ...
    ],
    "emphasis_areas": ["应强调的项目方向1", ...],
    "analysis_summary": "总体匹配度分析..."
}}
"""
    
    try:
        result = await invoke_structured(prompt, MatchAnalysisOutput, state.api_config, channel="match_analyst")
        state.jd_analysis = result.model_dump()
        logger.info(f"[Stage1] JD分析完成: 匹配度 {state.jd_analysis.get('match_score', 0)}%")
    except Exception as e:
        logger.error(f"[Stage1] JD分析失败: {e}")
        state.jd_analysis = {"error": str(e), "match_score": 0}
        state.errors.append(f"Stage1: {e}")
    
    return state


# ============================================================================
# 阶段2: 素材选择
# ============================================================================

async def stage2_material_selection(
    state: PipelineState,
    session_ids: List[str] = [],
    include_profile: bool = False,
) -> PipelineState:
    """
    阶段2: 候选人素材选择
    
    从统一素材池中选择相关素材：
    - 原始简历
    - 面试历史（QA 对话）
    - 分层画像
    - 项目改写历史
    
    输出：
    - 本次要使用的经历列表
    - 每条经历的证据来源
    - 允许推断范围 vs 必须用户确认的字段
    """
    material_pool = {
        "resume": state.resume_content,
        "interview_conversations": [],
        "profile": None,
        "allowed_inference_areas": [
            "语言润色", "STAR法则重构", "量化合理估算",
        ],
        "requires_confirmation_areas": [
            "新技能推断", "项目贡献角色变更", "公司/职位变更", "时间线修改"
        ],
    }
    
    # 加载面试对话
    if session_ids:
        try:
            from app.repositories.session.session_repo import SessionRepo
            service = SessionRepo()
            for sid in session_ids[:3]:
                conversations = await service.get_session_conversations(sid, state.user_id)
                if conversations:
                    material_pool["interview_conversations"].extend(conversations)
        except Exception as e:
            logger.warning(f"[Stage2] 加载面试对话失败: {e}")
    
    # 加载画像
    if include_profile:
        try:
            from app.repositories.session.session_repo import SessionRepo
            service = SessionRepo()
            profile_data = await service.get_user_profile(state.user_id)
            if profile_data:
                material_pool["profile"] = profile_data.get("profile")
        except Exception as e:
            logger.warning(f"[Stage2] 加载画像失败: {e}")
    
    state.material_pool = material_pool
    logger.info(f"[Stage2] 素材池构建完成: {len(material_pool['interview_conversations'])} 个QA对")
    
    return state


# ============================================================================
# 阶段3: 定制改写
# ============================================================================

async def stage3_custom_rewrite(state: PipelineState) -> PipelineState:
    """
    阶段3: 定制改写
    
    按模块改写，每条改写输出标准 ChangeItem：
    - 个人简介
    - 工作经历
    - 项目经历
    - 技术栈
    - 亮点总结
    
    每条 ChangeItem 必须包含：evidence_source, requires_user_confirmation, confidence
    """
    if not state.job_description:
        state.change_items = []
        return state
    
    jd_analysis = state.jd_analysis or {}
    material_pool = state.material_pool or {}
    
    # 构建面试洞察
    interview_section = ""
    conversations = material_pool.get("interview_conversations", [])
    if conversations:
        qa_texts = []
        for qa in conversations[:3]:
            q = qa.get('question', '') if isinstance(qa, dict) else getattr(qa, 'question', '')
            a = qa.get('answer', '') if isinstance(qa, dict) else getattr(qa, 'answer', '')
            qa_texts.append(f"Q: {q}\nA: {str(a)[:150]}...")
        interview_section = "\n\n【面试对话参考】：\n" + "\n".join(qa_texts)
    
    prompt = f"""你是一位「简历内容优化师」。请为以下简历提供具体的优化建议。

【目标职位】：
{state.job_description}

【当前简历】：
{state.resume_content[:2000]}

【JD分析结果】：
匹配度: {jd_analysis.get('match_score', 'N/A')}%
缺失关键词: {json.dumps(jd_analysis.get('missing_keywords', [])[:10], ensure_ascii=False)}
{interview_section}

请按模块输出具体的 ChangeItem 列表。每条改写必须包含完整的追踪信息。

【change_type 说明】：
- polish: 文字润色，不改变事实
- restructure: 重组内容结构
- suggest_addition: 建议新增内容（需用户确认是否有相关经历）
- fact_inference: 模型推断的事实（必须标记 requires_user_confirmation=true）

【evidence_source 填写规范】：
- JD关键词: 改写来自JD匹配分析
- 简历原文: 改写基于原简历内容
- 面试记录: 改写基于面试对话中展现的能力
- 画像: 改写基于候选人综合画像
- 用户补充: 基于用户手工补充的材料

请输出 JSON（change_items 数组）：
{{
    "change_items": [
        {{
            "section_name": "个人简介",
            "original_text": "原文（polish/restructure 时填写）",
            "optimized_text": "优化后内容",
            "change_type": "polish",
            "reason": "突出JD匹配的关键词",
            "evidence_source": "JD关键词",
            "requires_user_confirmation": false,
            "confidence": 0.95
        }},
        ...
    ]
}}
"""
    
    try:
        result = await invoke_structured(prompt, ContentSuggestionsOutput, state.api_config, channel="content_writer", max_retries=2)
        content = result.model_dump()
        items = content.get("change_items", [])
        state.change_items = items
        logger.info(f"[Stage3] 定制改写完成: {len(items)} 条 ChangeItem")
    except Exception as e:
        logger.error(f"[Stage3] 定制改写失败: {e}")
        state.change_items = []
        state.errors.append(f"Stage3: {e}")
    
    return state


# ============================================================================
# 阶段4: 简历组装
# ============================================================================

async def stage4_assemble(state: PipelineState) -> PipelineState:
    """
    阶段4: 整份简历组装
    
    把阶段3的模块产物组装成完整简历（Markdown）。
    不在这一步新增事实。
    """
    # 如果没有改写项，返回原始简历
    if not state.change_items:
        state.assembled_resume = state.resume_content
        return state
    
    # 基于 ChangeItems 和原始简历进行组装
    change_summary = "\n".join([
        f"- [{item.get('change_type', 'polish')}] {item.get('section_name', '')}: {item.get('optimized_text', '')[:100]}..."
        for item in state.change_items[:10]
    ])
    
    prompt = f"""你是一位「简历组装专家」。请根据原始简历和改写建议，组装一份完整的优化后简历。

【原始简历】：
{state.resume_content}

【改写建议】（共 {len(state.change_items)} 条）：
{change_summary}

【要求】：
1. 在原始简历基础上应用改写建议
2. 保持简历整体结构：个人简介 → 工作经历 → 项目经历 → 专业技能 → 教育背景
3. 不在这一步新增原始简历中没有的事实
4. 输出完整 Markdown 格式简历

请直接输出 Markdown 简历，不要用代码块包裹，禁止使用emoji表情。"""
    
    try:
        from app.services import llms
        from langchain_core.messages import HumanMessage
        
        fast_llm = llms.get_llm_for_request(state.api_config, channel="fast")
        response = await fast_llm.ainvoke([HumanMessage(content=prompt)])
        assembled = response.content.strip()
        
        # 清理可能的代码块包裹
        if assembled.startswith("```"):
            lines = assembled.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            assembled = "\n".join(lines)
        
        state.assembled_resume = assembled
        logger.info(f"[Stage4] 简历组装完成: {len(assembled)} 字符")
    except Exception as e:
        logger.error(f"[Stage4] 简历组装失败: {e}")
        state.assembled_resume = state.resume_content
        state.errors.append(f"Stage4: {e}")
    
    return state


# ============================================================================
# 阶段5: 事实核验
# ============================================================================

async def stage5_fact_check(state: PipelineState) -> PipelineState:
    """
    阶段5: 事实核验
    
    重点校验：
    - 是否引入了不存在的公司/职位/时间线
    - 是否把推断内容写成已确认事实
    - 是否过度夸大指标（如「提升200%」无据可查）
    - 是否强塞 JD 关键词导致失真
    
    对每条 fact_inference 类型的改写做强制复核。
    """
    from .resume_fact_policy import validate_change_items
    
    # 使用事实核验策略验证所有 ChangeItem
    fact_result = validate_change_items(
        state.change_items,
        state.resume_content,
        state.assembled_resume,
        state.job_description,
    )
    
    state.fact_check_result = fact_result
    
    # 识别高风险改写（fact_inference 或夸大检测）
    risky_items = [item for item in state.change_items
                   if item.get("change_type") == "fact_inference"
                   or item.get("requires_user_confirmation") == True]
    
    logger.info(
        f"[Stage5] 事实核验完成: "
        f"总改写 {len(state.change_items)} 条, "
        f"高风险 {len(risky_items)} 条, "
        f"风险标记 {len(fact_result.get('risk_flags', []))} 个"
    )
    
    return state


# ============================================================================
# 阶段6: 用户确认准备
# ============================================================================

async def stage6_confirmation_prep(state: PipelineState) -> PipelineState:
    """
    阶段6: 用户确认准备
    
    收集需要用户确认的改写项：
    - 新增的量化结果
    - 推断出的技能熟练度
    - 未在原简历出现但新写入的项目贡献
    - 涉及「主导/负责/独立完成」的高强度角色表述
    - 所有 requires_user_confirmation=True 的改写项
    """
    from .resume_fact_policy import REQUIRES_CONFIRMATION_KEYWORDS
    
    confirmation_items = []
    
    for item in state.change_items:
        needs_confirmation = (
            item.get("requires_user_confirmation", False)
            or item.get("change_type") == "fact_inference"
            or any(kw in str(item.get("optimized_text", ""))
                   for kw in REQUIRES_CONFIRMATION_KEYWORDS)
        )
        
        if needs_confirmation:
            confirmation_items.append({
                "section_name": item.get("section_name", ""),
                "change_type": item.get("change_type", ""),
                "original_text": item.get("original_text", ""),
                "optimized_text": item.get("optimized_text", ""),
                "reason": item.get("reason", ""),
                "evidence_source": item.get("evidence_source", ""),
                "confidence": item.get("confidence", 0.8),
            })
    
    state.confirmation_items = confirmation_items
    logger.info(f"[Stage6] 确认准备完成: {len(confirmation_items)} 项需要用户确认")
    
    return state


# ============================================================================
# 辅助函数
# ============================================================================

def _calc_confidence(change_items: List[dict]) -> float:
    """计算整体置信度"""
    if not change_items:
        return 1.0
    confidences = [item.get("confidence", 0.8) for item in change_items]
    return round(sum(confidences) / len(confidences), 2)
