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
        """初始化当前对象实例。"""
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
        """构建分析 Prompt"""

        # 格式化问答历史
        qa_text = "\n\n".join([
            f"Q{i+1}: {qa['question']}\nA{i+1}: {qa['answer']}"
            for i, qa in enumerate(context.qa_history)
        ])

        # 增量分析提示
        previous_hint = ""
        if context.previous_profile:
            previous_hint = f"""
【上一轮分析结果】：
- 专业能力: {context.previous_profile.professional_competence.score}/10
- 逻辑与问题解决: {context.previous_profile.logic_problem_solving.score}/10
- 沟通表达力: {context.previous_profile.communication.score}/10
请在此基础上进行增量更新。
"""

        prompt = f"""你是一位资深的技术面试官和人才评估专家。请对候选人进行全面、客观的多维度能力分析。

【简历信息】：
{context.resume}

【岗位要求】：
{context.job_description}

【公司背景】：
{context.company_info}

【面试问答记录】（共 {len(context.qa_history)} 轮）：
{qa_text}

{previous_hint}

【分析要求】：
请从以下 6 个维度对候选人进行评分和分析：

1. **专业能力 (professional_competence)**：
   - 核心技术栈掌握程度，底层原理理解。
   - 评分 0-10，需提供证据。

2. **执行与结果导向 (execution_results)**：
   - 是否有明确的目标感？能否克服困难拿到结果？
   - 评分 0-10，需提供证据。

3. **逻辑与问题解决 (logic_problem_solving)**：
   - 面对复杂问题的拆解能力，逻辑思维是否严密。
   - 评分 0-10，需提供证据。

4. **沟通表达力 (communication)**：
   - 表达是否清晰、准确、有条理。
   - 评分 0-10，需提供证据。

5. **成长潜力 (growth_potential)**：
   - 学习能力，对新技术的敏感度，反思复盘习惯。
   - 评分 0-10，需提供证据。

6. **协作能力 (collaboration)**：
   - 团队合作意识，换位思考能力。
   - 评分 0-10，需提供证据。

【技能标签】：
请提取用户最突出、最稳定的技能标签（如：Java, System Design, React 等），限制在 5-10 个。

【输出格式】：
请按要求输出结构化内容。JSON 结构如下：

{{
  "professional_competence": {{
    "score": 7.5,
    "evidence": "...",
    "reason": "评分原因说明",
    "better_answer_example": "更好的回答示例（可选）",
    "improvement_tip": "具体改进建议"
  }},
  "execution_results": {{
    "score": 8.0,
    "evidence": "...",
    "reason": "评分原因说明",
    "better_answer_example": "更好的回答示例（可选）",
    "improvement_tip": "具体改进建议"
  }},
  "logic_problem_solving": {{
    "score": 7.0,
    "evidence": "...",
    "reason": "评分原因说明",
    "better_answer_example": "更好的回答示例（可选）",
    "improvement_tip": "具体改进建议"
  }},
  "communication": {{
    "score": 6.5,
    "evidence": "...",
    "reason": "评分原因说明",
    "better_answer_example": "更好的回答示例（可选）",
    "improvement_tip": "具体改进建议"
  }},
  "growth_potential": {{
    "score": 8.5,
    "evidence": "...",
    "reason": "评分原因说明",
    "better_answer_example": "更好的回答示例（可选）",
    "improvement_tip": "具体改进建议"
  }},
  "collaboration": {{
    "score": 7.5,
    "evidence": "...",
    "reason": "评分原因说明",
    "better_answer_example": "更好的回答示例（可选）",
    "improvement_tip": "具体改进建议"
  }},
  "skill_tags": ["Java", "Spring Boot", "System Design"],
  "overall_assessment": "候选人整体表现...",
  "key_strengths": ["...", "..."],
  "key_weaknesses": ["...", "..."],
  "recommendation": "maybe",
  "confidence": 0.75,
  "last_updated": "{datetime.now().isoformat()}"
}}

【解释字段要求】：
- reason: 简要说明为什么给这个分数（1-2句话）
- better_answer_example: 如果该维度有明显不足，给出一个更好的回答示例；如果表现良好，可以省略
- improvement_tip: 针对该维度的具体改进建议（1句话）

请客观、公正地进行评估，避免主观臆断。"""

        return prompt

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
        candidate_profile: Optional[Dict[str, Any]] = None
    ) -> str:
        """构建短板地图分析 Prompt"""

        # 格式化问答历史
        qa_text = "\n\n".join([
            f"Q{i+1}: {qa['question']}\nA{i+1}: {qa['answer']}"
            for i, qa in enumerate(qa_history)
        ])

        # 画像上下文
        profile_hint = ""
        if candidate_profile:
            key_weaknesses = candidate_profile.get("key_weaknesses", [])
            if key_weaknesses:
                profile_hint = f"""
【已有能力画像中的薄弱项】：
{chr(10).join(f'- {w}' for w in key_weaknesses)}

请结合这些已知薄弱项进行更精准的短板分析。
"""

        prompt = f"""你是一位资深的技术面试复盘专家。请根据面试问答记录，生成一份详细的"面试短板地图"报告。

【简历信息】：
{resume}

【岗位要求】：
{job_description}

【公司背景】：
{company_info}

【面试问答记录】（共 {len(qa_history)} 轮）：
{qa_text}
{profile_hint}

【分析要求】：

1. **短板分类** (weakness_categories)：
   - 将短板归类到以下类别之一：基础概念、项目表达、系统设计、行为面试、沟通表达、压力应对
   - 每个类别给出具体描述和严重程度 (high/medium/low)
   - 分类不要超过 4 个，聚焦最关键的短板

2. **问题失败分析** (question_failures)：
   - 挑出 2-3 个回答最差的具体问题
   - 给出问题原文摘要、用户回答摘要、核心问题、更好的回答示例
   - 问题原文和用户回答摘要控制在 50 字以内

3. **改进行动项** (improvement_actions)：
   - 针对每个短板给出具体可执行的改进动作
   - 按优先级 1-5 排序（1 最高）
   - 估算投入时间

4. **推荐练习题** (recommended_questions)：
   - 推荐 3-5 道针对性的练习面试题
   - 题目应直接针对发现的短板

5. **优先级排序** (priority_order)：
   - 将短板类别按重要性排序

【输出格式】：
请按要求输出结构化内容。JSON 结构如下：

{{
  "weakness_categories": [
    {{
      "category": "基础概念",
      "description": "...",
      "severity": "high"
    }}
  ],
  "question_failures": [
    {{
      "question": "问题摘要",
      "user_answer": "回答摘要",
      "issue": "核心问题",
      "better_example": "更好的回答方向"
    }}
  ],
  "improvement_actions": [
    {{
      "action": "具体行动",
      "priority": 1,
      "estimated_effort": "1周"
    }}
  ],
  "recommended_questions": ["练习题1", "练习题2"],
  "priority_order": ["基础概念", "项目表达"]
}}

请客观、精准地分析，避免泛化建议。证据引用不要太长。"""

        return prompt

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
