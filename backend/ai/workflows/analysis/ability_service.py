"""
能力画像聚合服务
负责分析用户最近的面试表现，生成综合能力雷达图和技能标签
"""

import asyncio
import logging
from collections import Counter
from typing import Any, Dict, List, Optional

from ai.runtime.context_assembler import ContextAssembler, ContextSource
from ai.runtime.deadlines import TaskDeadline
from app.clock import utc_now
from app.config import get_settings
from app.db.repositories.session.session_repo import SessionRepo
from app.schemas.candidate_profile import CandidateProfile, DimensionScore

logger = logging.getLogger(__name__)


_DIMENSIONS = (
    "professional_competence",
    "execution_results",
    "logic_problem_solving",
    "communication",
    "growth_potential",
    "collaboration",
)


class AbilityAnalysisService:
    """能力画像聚合服务 - 基于数据库存储"""

    def __init__(self):
        """初始化 `AbilityAnalysisService` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端只在后续方法调用时承担访问边界。"""
        self.session_repo = SessionRepo()
        self._generate_lock = asyncio.Lock()
        self._last_generate_time = {}  # user_id -> timestamp
        self._cooldown_seconds = 60    # 60秒冷却时间

    async def get_overall_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        获取用户综合能力画像（从数据库读取）

        Returns:
            Optional[Dict]: 包含 profile 和 generated_at 的字典，如果不存在则返回 None
        """
        try:
            result = await self.session_repo.get_user_profile(user_id)
            return result  # 返回 {"profile": {...}, "updated_at": "..."}
        except Exception as e:
            logger.error("获取综合能力画像失败: %s", type(e).__name__)
            return None

    async def generate_overall_profile(self, user_id: str, api_config: Optional[Dict] = None) -> Dict[str, Any]:
        """
        生成用户综合能力画像（基于最近5个公司总画像，带时间权重）
        生成后存入数据库

        Args:
            user_id: 用户ID
            api_config: 用户API配置

        Returns:
            Dict: 包含 profile 和 warning (可选)
        """
        # 1. 检查并发锁
        if self._generate_lock.locked():
            raise ValueError("正在生成中，请稍候...")

        async with self._generate_lock:
            # 2. 检查冷却时间
            now = datetime.now().timestamp()
            last_time = self._last_generate_time.get(user_id, 0)
            if now - last_time < self._cooldown_seconds:
                remaining = int(self._cooldown_seconds - (now - last_time))
                raise ValueError(f"生成过于频繁，请等待 {remaining} 秒后再试")

            try:
                # 3. 获取最近5个已完成公司的总画像（每家公司只计入一次）
                recent_profiles = await self.session_repo.get_series_final_profiles(limit=5, user_id=user_id)

                if not recent_profiles:
                    logger.warning("无历史面试记录，无法生成综合画像")
                    return {"profile": self._get_empty_profile()}

                logger.info(f"开始聚合分析，共 {len(recent_profiles)} 个公司的总画像")

                # 4. 调用 LLM 进行时间加权聚合分析
                profile = await self._aggregate_profiles_with_weights(recent_profiles, api_config)

                # 5. 保存到数据库
                await self.session_repo.save_user_profile(profile.model_dump(), user_id)

                # 更新最后生成时间
                self._last_generate_time[user_id] = now

                logger.info("综合能力画像已生成并保存")

                result = {"profile": profile}

                # 添加警告信息（如果样本太少）
                if len(recent_profiles) < 3:
                    result["warning"] = f"当前仅基于 {len(recent_profiles)} 次面试记录，建议完成更多面试以获得更准确的评估。"

                return result

            except Exception as e:
                logger.error("生成综合能力画像失败: %s", type(e).__name__)
                # 降级方案：返回最近一次的画像
                fallback_profile = await self._fallback_to_latest(recent_profiles)
                return {
                    "profile": fallback_profile,
                    "warning": "生成失败，已显示最近一次面试结果。请稍后重试。"
                }

    async def aggregate_company_profile(
        self,
        round_profiles: List[Dict[str, Any]],
        api_config: Optional[Dict] = None,
    ) -> CandidateProfile:
        """Aggregate exactly three ordered round profiles into one company profile.

        The latest HR round receives the highest weight while the earlier rounds
        remain visible in scores, skills, strengths, weaknesses, and evidence.
        """
        if len(round_profiles) != 3:
            raise ValueError("公司总画像需要完整的三轮单轮画像")
        if any(profile.get("generation_mode") == "degraded_evidence_only" for profile in round_profiles):
            raise ValueError("公司总画像需要三轮均具备模型评审评分")
        return await self._aggregate_profiles_with_weights(list(reversed(round_profiles)), api_config)

    async def _aggregate_profiles_with_weights(
        self,
        profiles: List[Dict[str, Any]],
        api_config: Optional[Dict] = None,
    ) -> CandidateProfile:
        """Compute scores/trends locally and let the model write narrative fields only."""
        selected = [dict(profile) for profile in profiles[:5]]
        weights = [max(0.4, 1.0 - index * 0.15) for index in range(len(selected))]
        dimensions: dict[str, DimensionScore] = {}

        for dimension in _DIMENSIONS:
            values: list[tuple[float, float, dict[str, Any]]] = []
            for profile, weight in zip(selected, weights):
                raw = profile.get(dimension) or {}
                if not isinstance(raw, dict):
                    continue
                try:
                    score = float(raw.get("score", 0))
                except (TypeError, ValueError):
                    continue
                values.append((max(0.0, min(10.0, score)), weight, raw))
            if not values:
                dimensions[dimension] = DimensionScore(score=0, evidence="暂无该维度数据", trend="stable")
                continue
            weighted_score = sum(score * weight for score, weight, _raw in values) / sum(
                weight for _score, weight, _raw in values
            )
            latest = values[0][0]
            older = sum(score for score, _weight, _raw in values[1:]) / max(1, len(values) - 1)
            if len(values) <= 1 or abs(latest - older) < 0.5:
                trend = "stable"
            elif latest > older:
                trend = "improving"
            else:
                trend = "declining"
            evidence = next(
                (str(raw.get("evidence") or "")[:220] for _score, _weight, raw in values if raw.get("evidence")),
                f"基于 {len(values)} 次面试的时间加权结果",
            )
            dimensions[dimension] = DimensionScore(
                score=round(weighted_score, 2),
                evidence=evidence,
                trend=trend,
                reason=f"确定性时间加权，样本数 {len(values)}",
            )

        skill_counter: Counter[str] = Counter()
        strengths: list[str] = []
        weaknesses: list[str] = []
        total_questions = 0
        compact_profiles: list[dict[str, Any]] = []
        for index, profile in enumerate(selected):
            skills = [str(item)[:80] for item in profile.get("skill_tags") or [] if str(item).strip()]
            skill_counter.update(skills)
            strengths.extend(str(item)[:160] for item in profile.get("key_strengths") or [])
            weaknesses.extend(str(item)[:160] for item in profile.get("key_weaknesses") or [])
            total_questions += int(profile.get("total_questions_analyzed") or 0)
            compact_profiles.append({
                "index": index + 1,
                "weight": round(weights[index], 2),
                "scores": {
                    dimension: dimensions_source.get("score", 0)
                    for dimension in _DIMENSIONS
                    if isinstance((dimensions_source := profile.get(dimension)), dict)
                },
                "skills": skills[:12],
            })

        sorted_dimensions = sorted(
            dimensions.items(),
            key=lambda item: item[1].score,
            reverse=True,
        )
        local_strengths = list(dict.fromkeys([
            *strengths,
            *(name for name, score in sorted_dimensions[:2] if score.score >= 6),
        ]))[:5]
        local_weaknesses = list(dict.fromkeys([
            *weaknesses,
            *(name for name, score in sorted_dimensions[-2:] if score.score < 6),
        ]))[:5]
        average_score = sum(item.score for item in dimensions.values()) / len(_DIMENSIONS)
        from ai.workflows.analysis.multi_reviewer import AbilityConsensusOutput

        narrative = AbilityConsensusOutput(
            overall_assessment=f"综合能力时间加权均分 {average_score:.1f}/10。",
            key_strengths=local_strengths,
            key_weaknesses=local_weaknesses,
            recommendation="hire" if average_score >= 8 else ("maybe" if average_score >= 6 else "no_hire"),
            confidence=min(1.0, 0.35 + len(selected) * 0.13),
        )

        assembler = ContextAssembler(
            agent_name="ability_profile",
            total_model_chars=4500,
            source_budgets={"profile_summary": 4500},
        )
        assembled = assembler.assemble([
            ContextSource(
                name="profile_summary",
                content={
                    "sample_count": len(selected),
                    "weighted_dimensions": {
                        name: {"score": score.score, "trend": score.trend}
                        for name, score in dimensions.items()
                    },
                    "skill_frequency": skill_counter.most_common(15),
                    "profiles": compact_profiles,
                },
                trusted=True,
                required=True,
                max_chars=4500,
            )
        ])
        try:
            from ai.workflows.analysis.multi_reviewer import run_multi_reviewer_map_reduce

            from ai.workflows.analysis.reviewer_contexts import select_ability_reviewers

            reviewer_perspectives = select_ability_reviewers(selected)
            if not reviewer_perspectives:
                return self._get_empty_profile()
            consensus = await run_multi_reviewer_map_reduce(
                mode="ability_profile",
                review_context=assembled.model_context,
                reviewer_perspectives=reviewer_perspectives,
                api_config=api_config,
                deadline=TaskDeadline(float(get_settings().ability_profile_task_timeout_seconds)),
                call_metadata={
                    **assembled.model_event_fields(),
                    "reviewer_selection": list(reviewer_perspectives),
                    "reviewer_selection_policy": "evidence_coverage.v1",
                },
            )
            narrative = AbilityConsensusOutput.model_validate(consensus.output)
            logger.info(
                "能力画像多评审汇总完成: reviewer_count=%s successful=%s",
                len(consensus.assessments),
                sum(item.status == "success" for item in consensus.assessments),
            )
        except Exception as exc:
            logger.warning("能力画像多评审汇总降级: error_type=%s", type(exc).__name__)

        return CandidateProfile(
            **dimensions,
            skill_tags=[item for item, _count in skill_counter.most_common(20)],
            total_questions_analyzed=total_questions,
            last_updated=utc_now().isoformat(),
            overall_assessment=narrative.overall_assessment,
            key_strengths=narrative.key_strengths or local_strengths,
            key_weaknesses=narrative.key_weaknesses or local_weaknesses,
            recommendation=narrative.recommendation,
            confidence=narrative.confidence,
        )

    async def _fallback_to_latest(self, profiles: List[Dict[str, Any]]) -> CandidateProfile:
        """降级方案：返回最近一次的画像"""
        if not profiles:
            return self._get_empty_profile()

        try:
            latest_profile = profiles[0]
            logger.warning("使用降级方案：返回最近一次的面试画像")
            return CandidateProfile(**latest_profile)
        except Exception as e:
            logger.error("降级方案也失败: %s", type(e).__name__)
            return self._get_empty_profile()

    def _get_empty_profile(self) -> CandidateProfile:
        """返回空白画像（用于无数据场景）"""
        return CandidateProfile(
            professional_competence=DimensionScore(score=0, evidence="暂无数据"),
            execution_results=DimensionScore(score=0, evidence="暂无数据"),
            logic_problem_solving=DimensionScore(score=0, evidence="暂无数据"),
            communication=DimensionScore(score=0, evidence="暂无数据"),
            growth_potential=DimensionScore(score=0, evidence="暂无数据"),
            collaboration=DimensionScore(score=0, evidence="暂无数据"),
            skill_tags=[],
            overall_assessment="暂无面试记录，请先进行模拟面试。",
            last_updated=utc_now().isoformat()
        )


# 全局单例
_ability_service = None

def get_ability_service() -> AbilityAnalysisService:
    """读取 ability service，并通过 owner 或生命周期校验限制可见范围；资源不存在或状态不合法时返回稳定的业务结果或异常。"""
    global _ability_service
    if _ability_service is None:
        _ability_service = AbilityAnalysisService()
    return _ability_service
