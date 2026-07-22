"""
轮后总结与画像更新服务

每轮面试结束后执行：
1. 生成本轮面试总结
2. 触发分层画像更新（按轮次定位写入对应维度）
3. 触发短板地图分析
4. 更新会话状态

三轮定位 → 分层画像体系：
  第1轮（综合面）→ 基础素质画像（7维）
  第2轮（技术面）→ 技术深度画像（增量更新 + 跨轮趋势）
  第3轮（HR面）  → 软技能画像（+ 文化匹配度新维度）
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ============================================================================
# 分层画像维度定义
# ============================================================================

@dataclass
class ProfileLayer:
    """画像分层定义"""
    round_index: int
    round_name: str
    primary_dimensions: List[str]       # 本轮主评维度
    incremental_dimensions: List[str]   # 增量更新维度
    new_dimensions: List[str]           # 新增维度


# 三轮分层画像体系
LAYERED_PROFILE = {
    1: ProfileLayer(
        round_index=1,
        round_name="综合面",
        primary_dimensions=[
            "professional_competence",    # 专业基础能力
            "execution_results",          # 项目执行与成果
            "logic_problem_solving",      # 基础问题拆解能力
            "communication",              # 表达清晰度初评
            "growth_potential",           # 学习能力初评
            "collaboration",              # 团队协作初评
        ],
        incremental_dimensions=[],
        new_dimensions=["skill_tags"],    # 基础技能标签
    ),
    2: ProfileLayer(
        round_index=2,
        round_name="技术面",
        primary_dimensions=[
            "professional_competence",    # 技术深度升级（原理/系统设计/复杂度）
            "logic_problem_solving",      # 复杂问题拆解升级
            "execution_results",          # 项目细节真实性校验
        ],
        incremental_dimensions=[
            "skill_tags",                 # 技术栈标签补充
        ],
        new_dimensions=[
            "cross_round_trend",          # 跨轮趋势：第1轮→第2轮变化
        ],
    ),
    3: ProfileLayer(
        round_index=3,
        round_name="HR面",
        primary_dimensions=[
            "communication",              # 沟通表达最终评定
            "collaboration",              # 团队协作最终评定
            "growth_potential",           # 职业规划与成长潜力
        ],
        incremental_dimensions=[],
        new_dimensions=[
            "culture_fit",                # 文化匹配度（新增维度）
            "recommendation",             # 综合录用建议
        ],
    ),
}


# ============================================================================
# 综合汇总报告
# ============================================================================

async def generate_final_summary(
    session_series: List[str],
    user_id: str = "default_user",
    api_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    三轮结束后生成综合汇总报告。

    包含：
    - 三层画像汇总
    - 6维能力雷达图数据
    - 每轮评分变化趋势
    - 关键高光时刻
    - 持续性短板
    - 最终推荐结论

    Args:
        session_series: 三轮面试的 session_id 列表（按轮次顺序）
        user_id: 用户 ID
        api_config: API 配置

    Returns:
        综合汇总报告 dict
    """
    from app.infrastructure.db.repositories.session.session_repo import SessionRepo
    from app.infrastructure.db.repositories.interview.weakness_report_repo import get_weakness_report_repo

    session_repo = SessionRepo()
    weakness_repo = get_weakness_report_repo()

    round_profiles = []
    round_weaknesses = []
    all_skill_tags = []

    for sid in session_series:
        # 获取每轮画像
        profile = await session_repo.get_profile(sid)
        if profile:
            round_profiles.append(profile)
            tags = profile.get("skill_tags", [])
            all_skill_tags.extend(tags)

        # 获取每轮短板
        weakness = await weakness_repo.get_report_by_session(sid, user_id=user_id)
        if weakness:
            round_weaknesses.append(weakness.get("report_data", {}))

    # 计算趋势
    dimension_trends = _compute_dimension_trends(round_profiles)

    # 提取高光时刻和持续性短板
    highlights = _extract_highlights(round_profiles)
    persistent_weaknesses = _extract_persistent_weaknesses(round_weaknesses)

    # 生成推荐结论
    recommendation = _generate_recommendation(round_profiles, round_weaknesses)

    return {
        "round_count": len(session_series),
        "layered_profiles": round_profiles,
        "dimension_trends": dimension_trends,
        "radar_chart_data": _build_radar_data(round_profiles),
        "key_highlights": highlights,
        "persistent_weaknesses": persistent_weaknesses,
        "skill_tags": list(set(all_skill_tags)),
        "recommendation": recommendation,
    }


# ============================================================================
# 轮后处理入口
# ============================================================================

async def process_round_completion(
    session_id: str,
    user_id: str = "default_user",
    api_config: Optional[Dict[str, Any]] = None,
    trigger_analysis: bool = True,
    memory_context: Optional[str] = None,
) -> Dict[str, Any]:
    """
    处理单轮面试完成后的所有后续操作。

    执行顺序：
    1. 生成面试总结文本
    2. 更新会话状态为 completed
    3. 触发后台画像分析（分层写入）
    4. 触发后台短板地图分析

    Args:
        session_id: 会话 ID
        user_id: 用户 ID
        api_config: API 配置
        trigger_analysis: 是否触发后台分析
        memory_context: 长期记忆上下文

    Returns:
        包含 summary 和触发的后台任务信息
    """
    from app.workflows.interview.completion import process_interview_summary

    result = await process_interview_summary(
        session_id=session_id,
        messages=[],  # 从数据库读取
        mode="mock",
        api_config=api_config,
        trigger_analysis=trigger_analysis,
        memory_context=memory_context,
        user_id=user_id,
    )

    # 检查是否三轮完成，如果是则触发综合汇总
    await _check_series_completion(session_id, user_id, api_config)

    return {
        "summary": result,
        "session_id": session_id,
        "analyses_triggered": trigger_analysis,
    }


async def _check_series_completion(
    session_id: str,
    user_id: str,
    api_config: Optional[Dict[str, Any]] = None
):
    """检查多轮系列是否全部完成，如果是则生成最终汇总"""
    try:
        from app.infrastructure.db.repositories.session.session_repo import SessionRepo
        session_repo = SessionRepo()

        session = await session_repo.get_session(session_id, user_id=user_id)
        if not session:
            return

        series_id = session.metadata.series_id
        if not series_id:
            return

        # 查询同一 series 的所有会话
        # 如果三轮都已完成，生成综合汇总
        # （具体实现依赖数据库查询，此处为骨架）
        logger.info(f"[RoundSummary] 检查系列 {series_id} 是否全部完成")

    except Exception as e:
        logger.warning(f"[RoundSummary] 检查系列完成状态失败: {e}")


# ============================================================================
# 辅助函数
# ============================================================================

def _compute_dimension_trends(profiles: List[Dict]) -> Dict[str, List[float]]:
    """计算各维度在各轮的变化趋势"""
    if not profiles:
        return {}

    dimensions = [
        "professional_competence", "execution_results", "logic_problem_solving",
        "communication", "growth_potential", "collaboration"
    ]

    trends = {}
    for dim in dimensions:
        scores = []
        for profile in profiles:
            dim_data = profile.get(dim, {})
            if isinstance(dim_data, dict):
                scores.append(dim_data.get("score", 0))
            else:
                scores.append(0)
        trends[dim] = scores

    return trends


def _extract_highlights(profiles: List[Dict]) -> List[str]:
    """提取关键高光时刻"""
    highlights = []
    for i, profile in enumerate(profiles):
        strengths = profile.get("key_strengths", [])
        for s in strengths:
            highlights.append(f"第{i+1}轮: {s}")
    return highlights


def _extract_persistent_weaknesses(weaknesses: List[Dict]) -> List[str]:
    """提取持续性短板（在多轮中反复出现）"""
    from collections import Counter

    all_categories = []
    for w in weaknesses:
        for cat in w.get("weakness_categories", []):
            all_categories.append(cat.get("category", ""))

    # 出现 >= 2 次的视为持续性短板
    counter = Counter(all_categories)
    persistent = [cat for cat, count in counter.items() if count >= 2]

    return persistent


def _build_radar_data(profiles: List[Dict]) -> Dict[str, Any]:
    """构建6维能力雷达图数据"""
    if not profiles:
        return {"labels": [], "datasets": []}

    labels = ["专业能力", "执行成果", "逻辑解题", "沟通表达", "成长潜力", "协作能力"]
    dimension_keys = [
        "professional_competence", "execution_results", "logic_problem_solving",
        "communication", "growth_potential", "collaboration"
    ]

    datasets = []
    for i, profile in enumerate(profiles):
        scores = []
        for key in dimension_keys:
            dim_data = profile.get(key, {})
            if isinstance(dim_data, dict):
                scores.append(dim_data.get("score", 0) * 10)  # 0-10 → 0-100
            else:
                scores.append(0)
        datasets.append({
            "label": f"第{i+1}轮",
            "data": scores,
        })

    return {"labels": labels, "datasets": datasets}


def _generate_recommendation(profiles: List[Dict], weaknesses: List[Dict]) -> str:
    """生成最终推荐结论（hire / maybe / reject）"""
    if not profiles:
        return "maybe"

    # 取最后一轮画像的整体评估
    last_profile = profiles[-1]
    recommendation = last_profile.get("recommendation")

    if recommendation in ("hire", "maybe", "reject"):
        return recommendation

    # 基于分数推算
    avg_score = 0
    dim_count = 0
    dims = [
        "professional_competence", "execution_results", "logic_problem_solving",
        "communication", "growth_potential", "collaboration"
    ]
    for dim in dims:
        dim_data = last_profile.get(dim, {})
        if isinstance(dim_data, dict):
            avg_score += dim_data.get("score", 0)
            dim_count += 1

    if dim_count > 0:
        avg_score /= dim_count
        if avg_score >= 8:
            return "hire"
        elif avg_score >= 6:
            return "maybe"
        else:
            return "reject"

    return "maybe"
