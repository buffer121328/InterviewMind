"""
面试短板地图数据模型
用于面试后复盘的结构化短板分析
"""

from pydantic import BaseModel, Field
from typing import List, Optional


class WeaknessCategory(BaseModel):
    """短板分类"""
    category: str = Field(description="短板类别: 基础概念/项目表达/系统设计/行为面试/沟通表达/压力应对")
    description: str = Field(description="该类短板的具体描述")
    severity: str = Field(description="严重程度: high/medium/low")


class QuestionFailure(BaseModel):
    """具体问题失败分析"""
    question: str = Field(description="面试问题原文（简短摘要）")
    user_answer: str = Field(description="用户回答的关键内容（简短摘要）")
    issue: str = Field(description="回答中的核心问题")
    better_example: str = Field(description="更好的回答示例或改进方向")


class ImprovementAction(BaseModel):
    """改进行动项"""
    action: str = Field(description="具体改进行动")
    priority: int = Field(ge=1, le=5, description="优先级 1-5，1 最高")
    estimated_effort: str = Field(description="预估投入: 1天/1周/2周/1月")


class WeaknessReportData(BaseModel):
    """短板地图报告数据"""
    weakness_categories: List[WeaknessCategory] = Field(default_factory=list, description="短板分类列表")
    question_failures: List[QuestionFailure] = Field(default_factory=list, description="具体问题失败分析")
    improvement_actions: List[ImprovementAction] = Field(default_factory=list, description="改进行动项")
    recommended_questions: List[str] = Field(default_factory=list, description="推荐练习的面试题")
    priority_order: List[str] = Field(default_factory=list, description="按优先级排序的短板类别名称")


class WeaknessReport(BaseModel):
    """完整的短板地图报告"""
    id: Optional[int] = Field(default=None, description="报告 ID")
    user_id: str = Field(description="用户 ID")
    session_id: str = Field(description="会话 ID")
    series_id: Optional[str] = Field(default=None, description="系列 ID")
    report_data: WeaknessReportData = Field(description="报告数据")
    created_at: Optional[str] = Field(default=None, description="创建时间")
    updated_at: Optional[str] = Field(default=None, description="更新时间")
