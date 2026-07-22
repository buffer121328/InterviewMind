"""
统一报告结构模型
标准化所有报告输出，避免前端为不同接口写不同解析逻辑
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any


class UnifiedReport(BaseModel):
    """统一报告结构"""
    summary: str = Field(default="", description="总结摘要")
    strengths: List[str] = Field(default_factory=list, description="优势列表")
    risks: List[str] = Field(default_factory=list, description="风险点列表")
    weaknesses: List[str] = Field(default_factory=list, description="不足/短板列表")
    recommendations: List[str] = Field(default_factory=list, description="建议列表")
    next_actions: List[str] = Field(default_factory=list, description="下一步行动项")
    raw_data: Optional[Dict[str, Any]] = Field(default=None, description="原始数据（兼容旧结构）")


def normalize_to_unified_report(data: Dict[str, Any], report_type: str = "generic") -> UnifiedReport:
    """
    将不同来源的报告数据标准化为统一结构

    Args:
        data: 原始报告数据
        report_type: 报告类型 (profile/weakness/resume_optimize/jd_match)

    Returns:
        UnifiedReport: 标准化后的报告
    """
    report = UnifiedReport(raw_data=data)

    if report_type == "profile":
        report.summary = data.get("overall_assessment", "")
        report.strengths = data.get("key_strengths", [])
        report.weaknesses = data.get("key_weaknesses", [])
        report.recommendations = [data.get("recommendation", "")]
        report.risks = []
        report.next_actions = []

    elif report_type == "weakness":
        categories = data.get("weakness_categories", [])
        report.weaknesses = [c.get("description", "") for c in categories]
        report.risks = [c.get("category", "") for c in categories if c.get("severity") == "high"]
        actions = data.get("improvement_actions", [])
        report.next_actions = [a.get("action", "") for a in actions]
        report.recommendations = data.get("recommended_questions", [])
        report.summary = f"发现 {len(categories)} 个短板类别，{len(actions)} 个改进行动项"

    elif report_type == "resume_optimize":
        report.summary = data.get("overall_strategy", "")
        improvements = data.get("key_improvements", [])
        report.recommendations = [i.get("action", "") for i in improvements if isinstance(i, dict)]
        hr_feedback = data.get("hr_feedback", {})
        report.strengths = hr_feedback.get("highlights", [])
        report.risks = hr_feedback.get("concerns", [])
        report.weaknesses = []
        report.next_actions = []

    elif report_type == "jd_match":
        report.summary = f"匹配度: {data.get('overall_match_score', 0)}%"
        report.strengths = data.get("strengths", [])
        report.risks = data.get("risks", [])
        report.weaknesses = data.get("missing_keywords", [])
        report.recommendations = data.get("priority_actions", [])
        report.next_actions = data.get("priority_actions", [])

    return report
