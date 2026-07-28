"""
候选人画像分析服务
基于 Smart Model 进行深度、多维度分析
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

from app.schemas.candidate_profile import CandidateProfile, AnalysisContext, DimensionScore
from app.schemas.llm_outputs import CandidateProfileOutput, WeaknessReportOutput
from ai.llm.llm_utils import invoke_structured
from app.db.repositories.session.session_repo import SessionRepo

logger = logging.getLogger(__name__)


class CandidateAnalysisService:
    """候选人画像分析服务（后台异步运行）"""

    def __init__(self):
        """初始化 `CandidateAnalysisService` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端只在后续方法调用时承担访问边界。"""
        self.session_repo = SessionRepo()
        # 缓存：session_id -> CandidateProfile
        self._profile_cache: Dict[str, CandidateProfile] = {}

    async def analyze_candidate(
        self,
        session_id: str,
        resume: str,
        job_description: str,
        company_info: str,
        qa_history: List[Dict[str, str]],
        api_config: Optional[Dict] = None
    ) -> CandidateProfile:
        """
        异步分析候选人能力画像

        Args:
            session_id: 会话ID
            resume: 简历内容
            job_description: 岗位描述
            company_info: 公司信息
            qa_history: 问答历史 [{"question": "...", "answer": "..."}]
            api_config: 用户的 API 配置

        Returns:
            CandidateProfile: 更新后的能力画像
        """
        try:
            # 获取之前的画像（优先从缓存，其次从数据库）
            previous_profile = await self.get_cached_profile(session_id)

            # 构建分析上下文
            context = AnalysisContext(
                resume=resume,
                job_description=job_description,
                company_info=company_info,
                qa_history=qa_history,
                previous_profile=previous_profile
            )

            # 调用 Smart LLM 进行分析（使用用户配置的 API）
            profile = await self._perform_analysis(context, api_config)

            # 更新缓存
            self._profile_cache[session_id] = profile

            # 持久化到数据库
            await self.session_repo.save_profile(session_id, profile.model_dump())

            logger.info(f"[AnalysisService] 完成会话 {session_id} 的画像分析，共分析 {len(qa_history)} 轮对话")

            return profile

        except Exception as e:
            logger.error(f"[AnalysisService] 分析失败: {str(e)}")
            # 返回默认画像
            return self._get_default_profile()

    async def _perform_analysis(self, context: AnalysisContext, api_config: Optional[Dict] = None) -> CandidateProfile:
        """执行实际的 LLM 分析"""
        # 构建 Prompt
        prompt = self._build_analysis_prompt(context)

        try:
            result = await invoke_structured(prompt, CandidateProfileOutput, api_config, channel="smart")

            profile = CandidateProfile(
                professional_competence=DimensionScore(
                    score=result.professional_competence.score,
                    evidence=result.professional_competence.evidence,
                    reason=result.professional_competence.reason,
                    better_answer_example=result.professional_competence.better_answer_example,
                    improvement_tip=result.professional_competence.improvement_tip,
                ),
                execution_results=DimensionScore(
                    score=result.execution_results.score,
                    evidence=result.execution_results.evidence,
                    reason=result.execution_results.reason,
                    better_answer_example=result.execution_results.better_answer_example,
                    improvement_tip=result.execution_results.improvement_tip,
                ),
                logic_problem_solving=DimensionScore(
                    score=result.logic_problem_solving.score,
                    evidence=result.logic_problem_solving.evidence,
                    reason=result.logic_problem_solving.reason,
                    better_answer_example=result.logic_problem_solving.better_answer_example,
                    improvement_tip=result.logic_problem_solving.improvement_tip,
                ),
                communication=DimensionScore(
                    score=result.communication.score,
                    evidence=result.communication.evidence,
                    reason=result.communication.reason,
                    better_answer_example=result.communication.better_answer_example,
                    improvement_tip=result.communication.improvement_tip,
                ),
                growth_potential=DimensionScore(
                    score=result.growth_potential.score,
                    evidence=result.growth_potential.evidence,
                    reason=result.growth_potential.reason,
                    better_answer_example=result.growth_potential.better_answer_example,
                    improvement_tip=result.growth_potential.improvement_tip,
                ),
                collaboration=DimensionScore(
                    score=result.collaboration.score,
                    evidence=result.collaboration.evidence,
                    reason=result.collaboration.reason,
                    better_answer_example=result.collaboration.better_answer_example,
                    improvement_tip=result.collaboration.improvement_tip,
                ),
                skill_tags=result.skill_tags,
                total_questions_analyzed=0,
                last_updated=datetime.now().isoformat(),
                overall_assessment=result.overall_assessment,
                key_strengths=result.key_strengths,
                key_weaknesses=result.key_weaknesses,
                recommendation=result.recommendation,
                confidence=result.confidence,
            )

            logger.info(f"[AnalysisService] 成功解析画像数据")
            return profile
        except Exception as e:
            logger.error(f"[AnalysisService] 分析执行失败: {e}", exc_info=True)
            return self._get_default_profile()

    def _build_analysis_prompt(self, context: AnalysisContext) -> str:
        """Build the single-session profile prompt from trusted context fields."""
        from ai.prompts.analysis import build_candidate_analysis_prompt

        qa_text = "\n\n".join(
            f"Q{index + 1}: {item['question']}\nA{index + 1}: {item['answer']}"
            for index, item in enumerate(context.qa_history)
        )
        previous_hint = ""
        if context.previous_profile:
            previous_hint = (
                "【上一轮画像，仅作增量参考】\n"
                f"- 专业能力: {context.previous_profile.professional_competence.score}/10\n"
                f"- 逻辑与问题解决: {context.previous_profile.logic_problem_solving.score}/10\n"
                f"- 沟通表达力: {context.previous_profile.communication.score}/10"
            )
        return build_candidate_analysis_prompt(
            resume=context.resume,
            job_description=context.job_description,
            company_info=context.company_info,
            qa_text=qa_text,
            qa_count=len(context.qa_history),
            previous_hint=previous_hint,
        )

    def _get_default_profile(self) -> CandidateProfile:
        """返回默认画像（分析失败时使用）"""
        return CandidateProfile(
            professional_competence=DimensionScore(score=5.0, evidence="分析中..."),
            execution_results=DimensionScore(score=5.0, evidence="分析中..."),
            logic_problem_solving=DimensionScore(score=5.0, evidence="分析中..."),
            communication=DimensionScore(score=5.0, evidence="分析中..."),
            growth_potential=DimensionScore(score=5.0, evidence="分析中..."),
            collaboration=DimensionScore(score=5.0, evidence="分析中..."),
            skill_tags=[],
            total_questions_analyzed=0,
            last_updated=datetime.now().isoformat()
        )

    async def get_cached_profile(self, session_id: str) -> Optional[CandidateProfile]:
        """获取画像（缓存 -> 数据库）"""
        # 1. 查缓存
        if session_id in self._profile_cache:
            return self._profile_cache[session_id]

        # 2. 查数据库
        profile_data = await self.session_repo.get_profile(session_id)
        if profile_data:
            try:
                profile = CandidateProfile(**profile_data)
                self._profile_cache[session_id] = profile
                return profile
            except Exception as e:
                logger.error(f"反序列化画像失败: {e}")
                return None

        return None

    def clear_cache(self, session_id: str):
        """清除缓存"""
        if session_id in self._profile_cache:
            del self._profile_cache[session_id]


# 全局单例
_analysis_service = None

def get_analysis_service() -> CandidateAnalysisService:
    """获取分析服务单例"""
    global _analysis_service
    if _analysis_service is None:
        _analysis_service = CandidateAnalysisService()
    return _analysis_service


# ============================================================================
# 面试短板地图分析服务
# ============================================================================

class WeaknessAnalysisService:
    """面试短板地图分析服务"""

    async def generate_weakness_report(
        self,
        session_id: str,
        resume: str,
        job_description: str,
        company_info: str,
        qa_history: List[Dict[str, str]],
        candidate_profile: Optional[Dict[str, Any]] = None,
        api_config: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        生成面试短板地图报告

        Args:
            session_id: 会话 ID
            resume: 简历内容
            job_description: 岗位描述
            company_info: 公司信息
            qa_history: 问答历史
            candidate_profile: 已有的候选人画像（可选）
            api_config: API 配置

        Returns:
            短板地图报告数据字典
        """
        try:
            prompt = self._build_weakness_prompt(
                resume, job_description, company_info, qa_history, candidate_profile
            )

            result = await invoke_structured(prompt, WeaknessReportOutput, api_config, channel="smart")
            report_data = result.model_dump()

            logger.info(f"[WeaknessAnalysis] 成功生成短板地图，session={session_id}")
            return report_data

        except Exception as e:
            logger.error(f"[WeaknessAnalysis] 生成短板地图失败: {e}", exc_info=True)
            return self._get_default_report()

    def _build_weakness_prompt(
        self,
        resume: str,
        job_description: str,
        company_info: str,
        qa_history: List[Dict[str, str]],
        candidate_profile: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build the evidence-bounded weakness report prompt."""
        from ai.prompts.analysis import build_weakness_analysis_prompt

        qa_text = "\n\n".join(
            f"Q{index + 1}: {item['question']}\nA{index + 1}: {item['answer']}"
            for index, item in enumerate(qa_history)
        )
        weaknesses = (candidate_profile or {}).get("key_weaknesses", [])
        profile_hint = ""
        if weaknesses:
            profile_hint = "【已有画像薄弱项，仅供交叉验证】\n" + "\n".join(
                f"- {item}" for item in weaknesses[:5]
            )
        return build_weakness_analysis_prompt(
            resume=resume,
            job_description=job_description,
            company_info=company_info,
            qa_text=qa_text,
            qa_count=len(qa_history),
            profile_hint=profile_hint,
        )

    def _get_default_report(self) -> Dict[str, Any]:
        """返回默认报告（分析失败时使用）"""
        return {
            "weakness_categories": [],
            "question_failures": [],
            "improvement_actions": [],
            "recommended_questions": [],
            "priority_order": []
        }


# 全局单例
_weakness_analysis_service = None

def get_weakness_analysis_service() -> WeaknessAnalysisService:
    """获取短板分析服务单例"""
    global _weakness_analysis_service
    if _weakness_analysis_service is None:
        _weakness_analysis_service = WeaknessAnalysisService()
    return _weakness_analysis_service
