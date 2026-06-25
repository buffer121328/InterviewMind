"""
LLM 结构化输出模型集中定义
所有 LLM 调用的 Pydantic 输出模型统一管理，配合 with_structured_output 使用
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any


# ============================================================================
# 面试规划相关输出
# ============================================================================

class InterviewQuestionItem(BaseModel):
    """单个面试问题"""
    id: int = Field(description="题目序号")
    topic: str = Field(description="考察主题，如Java并发")
    content: str = Field(description="具体的问题描述")
    type: str = Field(description="题目类型：intro, tech, behavior, system_design")
    target_skill: Optional[str] = Field(default=None, description="目标技能")
    sources: List[Dict[str, Any]] = Field(default_factory=list, description="证据来源")
    reason: Optional[str] = Field(default=None, description="为什么问这道题")
    fallback_reason: Optional[str] = Field(default=None, description="回退原因")


class PlanOutput(BaseModel):
    """面试规划输出"""
    questions: List[InterviewQuestionItem] = Field(description="面试问题列表")


class SimpleQuestionItem(BaseModel):
    """简单格式的面试问题（用于语音面试等）"""
    topic: str = Field(description="考察主题")
    content: str = Field(description="具体问题内容")


class SimplePlanOutput(BaseModel):
    """简单格式的面试规划输出"""
    questions: List[SimpleQuestionItem] = Field(description="面试问题列表")


class HintOutput(BaseModel):
    """回答提示输出"""
    hints: List[str] = Field(description="每道题的回答提示")


# ============================================================================
# 简历优化器相关输出
# ============================================================================

class MatchAnalysisOutput(BaseModel):
    """匹配分析师输出"""
    jd_keywords: List[str] = Field(default_factory=list, description="JD 关键词")
    matched_keywords: List[str] = Field(default_factory=list, description="匹配的关键词")
    missing_keywords: List[str] = Field(default_factory=list, description="缺失的关键词")
    bonus_items: List[str] = Field(default_factory=list, description="加分项")
    match_score: float = Field(default=0, description="匹配度百分比")
    analysis_summary: str = Field(default="", description="总体匹配度分析")


class ChangeItem(BaseModel):
    """变更项 — 标准化简历改写追踪"""
    section_name: str = Field(description="所属模块（工作经历/项目经历/个人简介等）")
    original_text: Optional[str] = Field(default=None, description="原文（polish/restructure 时有值）")
    optimized_text: str = Field(description="优化后内容")
    change_type: str = Field(
        description="变更类型: polish(润色)/restructure(重组)/suggest_addition(建议新增)/fact_inference(模型推断)"
    )
    reason: str = Field(default="", description="变更原因说明")
    evidence_source: str = Field(
        default="",
        description="证据来源：JD关键词 / 简历原文 / 面试记录 / 画像 / 用户补充"
    )
    requires_user_confirmation: bool = Field(
        default=False,
        description="是否需要用户确认（fact_inference 类型必须为 True）"
    )
    confidence: float = Field(default=0.8, description="置信度 0-1")


class SectionSuggestion(BaseModel):
    """章节优化建议"""
    section_name: str = Field(description="部分名称")
    current_issues: List[str] = Field(default_factory=list, description="当前问题")
    suggestions: List[str] = Field(default_factory=list, description="优化建议")
    rewrite_example: Optional[str] = Field(default=None, description="重写示例")
    change_type: str = Field(default="polish", description="变更类型")
    confidence: float = Field(default=0.8, description="置信度")
    requires_user_confirmation: bool = Field(default=False, description="是否需要用户确认")


class ContentSuggestionsOutput(BaseModel):
    """内容优化师输出"""
    sections: List[SectionSuggestion] = Field(default_factory=list, description="各部分优化建议")
    quantification_tips: List[str] = Field(default_factory=list, description="可量化建议")
    highlight_recommendations: List[str] = Field(default_factory=list, description="亮点建议")
    interview_insights: Optional[str] = Field(default=None, description="面试洞察")
    change_items: List[ChangeItem] = Field(default_factory=list, description="变更项列表")


class ContentConciseness(BaseModel):
    """内容精炼度评估"""
    score: float = Field(default=7, description="精炼度评分")
    is_concise: bool = Field(default=True, description="是否精炼")
    issues: List[str] = Field(default_factory=list, description="冗余问题")
    redundant_sections: List[str] = Field(default_factory=list, description="可精简部分")
    suggestion: Optional[str] = Field(default=None, description="精简建议")


class FirstImpression(BaseModel):
    """第一印象评估"""
    score: float = Field(default=7, description="评分")
    comment: str = Field(default="", description="评价")


class HRReviewOutput(BaseModel):
    """HR审核官输出"""
    first_impression: FirstImpression = Field(default_factory=FirstImpression, description="第一印象")
    hard_requirements_met: bool = Field(default=True, description="是否满足硬性要求")
    hard_requirements_issues: List[str] = Field(default_factory=list, description="硬性要求问题")
    highlights: List[str] = Field(default_factory=list, description="亮点")
    concerns: List[str] = Field(default_factory=list, description="疑虑点")
    pass_rate_estimate: float = Field(default=70, description="通过率预估")
    content_conciseness: ContentConciseness = Field(default_factory=ContentConciseness, description="内容精炼度")
    improvement_priority: List[str] = Field(default_factory=list, description="改进优先级")
    overall_recommendation: str = Field(default="", description="整体推荐")


class KeyImprovement(BaseModel):
    """关键改进点"""
    priority: int = Field(description="优先级")
    area: str = Field(description="改进领域")
    issue: str = Field(description="问题描述")
    action: str = Field(description="改进行动")
    example: Optional[str] = Field(default=None, description="具体示例")


class OptimizedSection(BaseModel):
    """优化后的章节"""
    section_name: str = Field(description="部分名称")
    original_issues: List[str] = Field(default_factory=list, description="原始问题")
    optimized_content: str = Field(description="优化后的内容")


class ModeratorSummaryOutput(BaseModel):
    """主持人整合输出"""
    match_score: float = Field(default=0, description="匹配度")
    hr_pass_rate: float = Field(default=0, description="HR通过率")
    key_improvements: List[KeyImprovement] = Field(default_factory=list, description="关键改进点")
    optimized_sections: List[OptimizedSection] = Field(default_factory=list, description="优化后的章节")
    keyword_recommendations: List[str] = Field(default_factory=list, description="关键词建议")
    overall_strategy: str = Field(default="", description="总体优化策略")


class ReflectionOutput(BaseModel):
    """反思节点输出"""
    issues_found: List[str] = Field(default_factory=list, description="发现的问题")
    additional_suggestions: List[str] = Field(default_factory=list, description="额外建议")
    risk_warnings: List[str] = Field(default_factory=list, description="风险提示")
    final_adjustments: List[str] = Field(default_factory=list, description="最终调整")
    quality_score: float = Field(default=80, description="质量评分")
    approval: bool = Field(default=True, description="是否通过")


class RefinedResultOutput(BaseModel):
    """精炼节点输出"""
    match_score: float = Field(default=0, description="匹配度")
    hr_pass_rate: float = Field(default=0, description="HR通过率")
    key_improvements: List[KeyImprovement] = Field(default_factory=list, description="关键改进点")
    optimized_sections: List[OptimizedSection] = Field(default_factory=list, description="优化后的章节")
    keyword_recommendations: List[str] = Field(default_factory=list, description="关键词建议")
    overall_strategy: str = Field(default="", description="总体优化策略")
    refinement_notes: Optional[str] = Field(default=None, description="精炼说明")
    change_items: List[ChangeItem] = Field(default_factory=list, description="变更项")


# ============================================================================
# 简历生成相关输出
# ============================================================================

class NeedsAnalysisOutput(BaseModel):
    """需求分析输出"""
    has_gaps: bool = Field(default=False, description="是否有信息缺口")
    questions: List[str] = Field(default_factory=list, description="需要确认的问题")


class OptimizationSummary(BaseModel):
    """优化摘要"""
    missing_info_fixed: List[str] = Field(default_factory=list, description="补充的遗漏信息")
    content_refined: List[str] = Field(default_factory=list, description="内容精炼")
    skills_focused: List[str] = Field(default_factory=list, description="技能聚焦")
    keywords_added: List[str] = Field(default_factory=list, description="添加的关键词")
    improvements_applied: List[str] = Field(default_factory=list, description="已应用的改进")


class QualityScores(BaseModel):
    """质量评分"""
    completeness: float = Field(default=80, description="完整度")
    conciseness: float = Field(default=80, description="精炼度")
    focus: float = Field(default=80, description="聚焦度")
    keyword_coverage: float = Field(default=80, description="关键词覆盖率")
    jd_match: float = Field(default=80, description="JD匹配度")


class DraftOptimizationOutput(BaseModel):
    """初稿优化输出"""
    optimized_content: str = Field(description="优化后的完整 Markdown 简历")
    optimization_summary: OptimizationSummary = Field(default_factory=OptimizationSummary, description="优化摘要")
    quality_scores: QualityScores = Field(default_factory=QualityScores, description="质量评分")


class RiskDetail(BaseModel):
    """风险详情"""
    type: str = Field(default="excessive_fabrication", description="风险类型")
    location: str = Field(description="具体位置")
    original: str = Field(default="无相关描述", description="原始内容")
    fabricated: str = Field(description="造假内容")
    reason: str = Field(description="判定理由")


class FactCheckOutput(BaseModel):
    """风控核查输出"""
    is_excessive: bool = Field(default=False, description="是否过度造假")
    risk_details: List[RiskDetail] = Field(default_factory=list, description="风险详情")


class FinalReviewOutput(BaseModel):
    """终审输出"""
    final_content: str = Field(description="最终修订后的完整 Markdown 简历")
    review_passed: bool = Field(default=True, description="审查是否通过")
    modification_notes: List[str] = Field(default_factory=list, description="修改说明")
    title: str = Field(default="新简历", description="简历标题")


# ============================================================================
# 简历分析相关输出
# ============================================================================

class DimensionScoreItem(BaseModel):
    """维度评分项"""
    score: float = Field(description="评分 (0-100)")
    comment: str = Field(description="评价说明")


class ResumeAnalysisOutput(BaseModel):
    """简历分析输出"""
    dimension_scores: Dict[str, DimensionScoreItem] = Field(description="各维度评分")
    strengths: List[str] = Field(default_factory=list, description="优势")
    weaknesses: List[str] = Field(default_factory=list, description="不足")
    priority_improvements: List[str] = Field(default_factory=list, description="优先改进建议")
    interview_insights: Optional[str] = Field(default=None, description="基于面试的洞察")


# ============================================================================
# 候选人画像分析相关输出
# ============================================================================

class DimensionAnalysis(BaseModel):
    """维度分析结果"""
    score: float = Field(description="评分 (0-10)")
    evidence: str = Field(description="支撑证据")
    reason: Optional[str] = Field(default=None, description="评分原因")
    better_answer_example: Optional[str] = Field(default=None, description="更好的回答示例")
    improvement_tip: Optional[str] = Field(default=None, description="改进建议")


class CandidateProfileOutput(BaseModel):
    """候选人画像输出"""
    professional_competence: DimensionAnalysis = Field(description="专业能力")
    execution_results: DimensionAnalysis = Field(description="执行与结果导向")
    logic_problem_solving: DimensionAnalysis = Field(description="逻辑与问题解决")
    communication: DimensionAnalysis = Field(description="沟通表达力")
    growth_potential: DimensionAnalysis = Field(description="成长潜力")
    collaboration: DimensionAnalysis = Field(description="协作能力")
    skill_tags: List[str] = Field(default_factory=list, description="技能标签")
    overall_assessment: Optional[str] = Field(default=None, description="整体评价")
    key_strengths: List[str] = Field(default_factory=list, description="主要优势")
    key_weaknesses: List[str] = Field(default_factory=list, description="主要不足")
    recommendation: Optional[str] = Field(default=None, description="录用建议")
    confidence: Optional[float] = Field(default=None, description="推荐置信度")


# ============================================================================
# 短板地图分析相关输出
# ============================================================================

class WeaknessCategory(BaseModel):
    """短板类别"""
    category: str = Field(description="类别名称")
    description: str = Field(description="具体描述")
    severity: str = Field(description="严重程度: high/medium/low")


class QuestionFailure(BaseModel):
    """问题失败分析"""
    question: str = Field(description="问题摘要")
    user_answer: str = Field(description="回答摘要")
    issue: str = Field(description="核心问题")
    better_example: str = Field(description="更好的回答方向")


class ImprovementAction(BaseModel):
    """改进行动项"""
    action: str = Field(description="具体行动")
    priority: int = Field(description="优先级 (1-5)")
    estimated_effort: str = Field(description="估算投入时间")


class WeaknessReportOutput(BaseModel):
    """短板地图报告输出"""
    weakness_categories: List[WeaknessCategory] = Field(default_factory=list, description="短板类别")
    question_failures: List[QuestionFailure] = Field(default_factory=list, description="问题失败分析")
    improvement_actions: List[ImprovementAction] = Field(default_factory=list, description="改进行动项")
    recommended_questions: List[str] = Field(default_factory=list, description="推荐练习题")
    priority_order: List[str] = Field(default_factory=list, description="优先级排序")


# ============================================================================
# JD 匹配分析相关输出
# ============================================================================

class JDMatchLLMOutput(BaseModel):
    """JD 匹配分析输出"""
    skill_match_score: float = Field(description="技能匹配分 (0-100)")
    skill_match_comment: str = Field(description="技能匹配评价")
    project_match_score: float = Field(description="项目匹配分 (0-100)")
    project_match_comment: str = Field(description="项目匹配评价")
    experience_match_score: float = Field(description="经验匹配分 (0-100)")
    experience_match_comment: str = Field(description="经验匹配评价")
    education_match_score: float = Field(description="教育匹配分 (0-100)")
    education_match_comment: str = Field(description="教育匹配评价")
    matched_keywords: List[str] = Field(default_factory=list, description="匹配的关键词")
    missing_keywords: List[str] = Field(default_factory=list, description="缺失的关键词")
    strengths: List[str] = Field(default_factory=list, description="优势")
    risks: List[str] = Field(default_factory=list, description="风险/短板")
    priority_actions: List[str] = Field(default_factory=list, description="优先改进动作")
    selection_hints: Dict[str, Any] = Field(default_factory=dict, description="素材筛选提示")


# ============================================================================
# BOSS 推荐页批量抓取相关输出（半自动化）
# ============================================================================

class JobCardItem(BaseModel):
    """单个岗位卡片（从 BOSS 推荐页提取）"""
    company_name: str = Field(description="公司名")
    job_title: str = Field(description="岗位名称")
    salary_text: str = Field(default="", description="薪资文本，如 15-30K")
    city: str = Field(default="", description="工作城市/区域")
    title_summary: str = Field(default="", description="卡片标题行的额外信息（经验/学历要求）")
    job_description: str = Field(default="", description="卡片可见的简短 JD 描述（推荐页通常只有 1-3 行）")


class JobCardList(BaseModel):
    """BOSS 推荐页岗位卡片列表"""
    cards: List[JobCardItem] = Field(default_factory=list, description="前 N 个推荐岗位")
