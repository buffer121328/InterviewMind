"""
分层画像体系测试

验证：
- 三轮面试画像维度正确性
- 基础素质画像（第1轮）
- 技术深度画像（第2轮，增量更新）
- 软技能画像（第3轮，新增维度）
- 综合汇总报告生成
"""

import pytest
from unittest.mock import AsyncMock, patch
from app.agents.interview.round_summary_service import (
    LAYERED_PROFILE,
    ProfileLayer,
    generate_final_summary,
    _compute_dimension_trends,
    _extract_highlights,
    _extract_persistent_weaknesses,
    _build_radar_data,
    _generate_recommendation,
)


# ============================================================================
# 模拟画像数据
# ============================================================================

MOCK_PROFILE_ROUND1 = {
    "professional_competence": {"score": 7, "evidence": "基础知识扎实"},
    "execution_results": {"score": 6, "evidence": "项目成果描述清晰"},
    "logic_problem_solving": {"score": 7, "evidence": "问题拆解合理"},
    "communication": {"score": 6, "evidence": "表达基本清晰"},
    "growth_potential": {"score": 7, "evidence": "有学习意愿"},
    "collaboration": {"score": 6, "evidence": "团队经验提及"},
    "skill_tags": ["Java", "Spring Boot", "MySQL"],
    "key_strengths": ["基础扎实", "项目经验丰富"],
    "key_weaknesses": ["系统设计能力待提升"],
    "overall_assessment": "基础素质良好",
}

MOCK_PROFILE_ROUND2 = {
    "professional_competence": {"score": 8, "evidence": "对原理有深入理解"},
    "execution_results": {"score": 7, "evidence": "项目细节验证通过"},
    "logic_problem_solving": {"score": 8, "evidence": "复杂场景拆解能力强"},
    "communication": {"score": 6, "evidence": "技术表达尚可"},
    "growth_potential": {"score": 7, "evidence": "持续学习"},
    "collaboration": {"score": 7, "evidence": "提到跨团队协作"},
    "skill_tags": ["Java", "Spring Boot", "MySQL", "Redis", "微服务"],
    "key_strengths": ["技术深度好", "架构思维强"],
    "key_weaknesses": ["沟通需加强"],
    "overall_assessment": "技术深度良好",
}

MOCK_PROFILE_ROUND3 = {
    "professional_competence": {"score": 8, "evidence": "技术能力确认"},
    "execution_results": {"score": 7, "evidence": "成果导向明确"},
    "logic_problem_solving": {"score": 8, "evidence": "逻辑清晰"},
    "communication": {"score": 8, "evidence": "表达清晰到位"},
    "growth_potential": {"score": 9, "evidence": "职业规划明确"},
    "collaboration": {"score": 8, "evidence": "团队适应性好"},
    "culture_fit": {"score": 8, "evidence": "文化匹配度高"},
    "recommendation": "hire",
    "confidence": 0.85,
    "skill_tags": ["Java", "Spring Boot", "MySQL", "Redis", "微服务", "K8s"],
    "key_strengths": ["综合能力强", "可录用"],
    "key_weaknesses": [],
    "overall_assessment": "综合素质优秀，推荐录用",
}

MOCK_WEAKNESSES = [
    {
        "weakness_categories": [
            {"category": "系统设计", "severity": "medium", "description": "分布式系统设计不足"},
            {"category": "沟通表达", "severity": "low", "description": "技术描述不够凝练"},
        ]
    },
    {
        "weakness_categories": [
            {"category": "系统设计", "severity": "medium", "description": "高并发场景经验不足"},
            {"category": "项目管理", "severity": "low", "description": "缺少项目排期经验"},
        ]
    },
    {
        "weakness_categories": [
            {"category": "项目管理", "severity": "low", "description": "团队管理经验初评"},
        ]
    },
]


# ============================================================================
# 分层画像结构测试
# ============================================================================

class TestLayeredProfileStructure:
    """分层画像体系结构测试"""

    def test_round1_primary_dimensions(self):
        """第1轮主评7个维度"""
        layer = LAYERED_PROFILE[1]
        assert layer.round_name == "综合面"
        assert len(layer.primary_dimensions) == 6  # 6个主维度
        assert "professional_competence" in layer.primary_dimensions
        assert "skill_tags" in layer.new_dimensions

    def test_round2_primary_dimensions(self):
        """第2轮主评3个维度 + 跨轮趋势"""
        layer = LAYERED_PROFILE[2]
        assert layer.round_name == "技术面"
        assert len(layer.primary_dimensions) == 3
        assert "cross_round_trend" in layer.new_dimensions

    def test_round3_primary_dimensions(self):
        """第3轮主评3个维度 + 文化匹配度"""
        layer = LAYERED_PROFILE[3]
        assert layer.round_name == "HR面"
        assert len(layer.primary_dimensions) == 3
        assert "culture_fit" in layer.new_dimensions
        assert "recommendation" in layer.new_dimensions

    def test_all_rounds_defined(self):
        """三轮画像都已定义"""
        assert 1 in LAYERED_PROFILE
        assert 2 in LAYERED_PROFILE
        assert 3 in LAYERED_PROFILE


# ============================================================================
# 趋势计算测试
# ============================================================================

class TestDimensionTrends:
    """维度趋势计算测试"""

    def test_compute_trends(self):
        profiles = [MOCK_PROFILE_ROUND1, MOCK_PROFILE_ROUND2, MOCK_PROFILE_ROUND3]
        trends = _compute_dimension_trends(profiles)

        assert "professional_competence" in trends
        assert trends["professional_competence"] == [7, 8, 8]

    def test_empty_profiles(self):
        trends = _compute_dimension_trends([])
        assert trends == {}

    def test_single_profile(self):
        trends = _compute_dimension_trends([MOCK_PROFILE_ROUND1])
        assert trends["professional_competence"] == [7]


# ============================================================================
# 高光时刻提取测试
# ============================================================================

class TestHighlights:
    """高光时刻提取测试"""

    def test_extract_highlights(self):
        profiles = [MOCK_PROFILE_ROUND1, MOCK_PROFILE_ROUND2]
        highlights = _extract_highlights(profiles)

        assert len(highlights) >= 2
        assert "第1轮" in highlights[0]

    def test_empty_profiles(self):
        highlights = _extract_highlights([])
        assert highlights == []


# ============================================================================
# 持续性短板测试
# ============================================================================

class TestPersistentWeaknesses:
    """持续性短板识别测试"""

    def test_identify_persistent(self):
        persistent = _extract_persistent_weaknesses(MOCK_WEAKNESSES[:2])

        # "系统设计" 出现了2次，应该被识别为持续性短板
        assert "系统设计" in persistent

    def test_no_persistent(self):
        """出现不足2次的不算持续性"""
        single_weakness = [
            {"weakness_categories": [{"category": "沟通表达", "severity": "low"}]}
        ]
        persistent = _extract_persistent_weaknesses(single_weakness)
        assert "沟通表达" not in persistent


# ============================================================================
# 雷达图测试
# ============================================================================

class TestRadarData:
    """雷达图数据构建测试"""

    def test_build_radar_data(self):
        profiles = [MOCK_PROFILE_ROUND1, MOCK_PROFILE_ROUND2]
        radar = _build_radar_data(profiles)

        assert len(radar["labels"]) == 6
        assert len(radar["datasets"]) == 2
        assert radar["datasets"][0]["label"] == "第1轮"

    def test_empty_radar(self):
        radar = _build_radar_data([])
        assert radar["labels"] == []
        assert radar["datasets"] == []


# ============================================================================
# 推荐结论测试
# ============================================================================

class TestRecommendation:
    """推荐结论生成测试"""

    def test_hire_recommendation(self):
        result = _generate_recommendation(
            [MOCK_PROFILE_ROUND1, MOCK_PROFILE_ROUND2, MOCK_PROFILE_ROUND3],
            MOCK_WEAKNESSES,
        )
        assert result == "hire"

    def test_maybe_recommendation(self):
        profile = {
            "professional_competence": {"score": 6},
            "execution_results": {"score": 6},
            "logic_problem_solving": {"score": 6},
            "communication": {"score": 6},
            "growth_potential": {"score": 6},
            "collaboration": {"score": 6},
            "recommendation": "maybe",
        }
        result = _generate_recommendation([profile], [])
        assert result == "maybe"

    def test_reject_recommendation(self):
        profile = {
            "professional_competence": {"score": 3},
            "execution_results": {"score": 4},
            "logic_problem_solving": {"score": 3},
            "communication": {"score": 4},
            "growth_potential": {"score": 3},
            "collaboration": {"score": 4},
        }
        result = _generate_recommendation([profile], [])
        assert result == "reject"

    def test_invalid_recommendation_falls_back_to_scores(self):
        profile = {
            "professional_competence": {"score": 9},
            "execution_results": {"score": 8},
            "logic_problem_solving": {"score": 8},
            "communication": {"score": 8},
            "growth_potential": {"score": 8},
            "collaboration": {"score": 8},
            "recommendation": "unknown",
        }

        result = _generate_recommendation([profile], [])

        assert result == "hire"
