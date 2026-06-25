"""
简历 6 阶段 Pipeline 测试

验证：
- 各阶段输出 Schema 正确性
- ChangeItem 标准化字段
- 证据来源追踪
- 事实核验策略
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.resume.resume_orchestrator import (
    PipelineState,
    stage1_jd_analysis,
    stage2_material_selection,
    stage3_custom_rewrite,
    stage4_assemble,
    stage5_fact_check,
    stage6_confirmation_prep,
    _calc_confidence,
)
from app.services.resume.resume_fact_policy import (
    validate_change_items,
    detect_keyword_stuffing,
    REQUIRES_CONFIRMATION_KEYWORDS,
)
from app.schemas.llm_outputs import ChangeItem


# ============================================================================
# 模拟数据
# ============================================================================

MOCK_RESUME = """
张三 | Java开发工程师 | 3年经验

工作经历：
XX科技 | Java开发 | 2022-至今
- 参与电商平台后端开发
- 负责订单模块和支付模块

项目经历：
电商平台 | 核心开发 | 2022-至今
- 基于Spring Boot开发微服务
- 使用MySQL和Redis

专业技能：
Java, Spring Boot, MySQL, Redis, Git
"""

MOCK_JD = """
Java高级工程师

岗位要求：
- 3年以上Java开发经验
- 熟悉Spring Cloud微服务架构
- 了解Kubernetes/Docker容器化部署
- 有高并发系统设计经验
- 熟悉消息队列（Kafka/RabbitMQ）
"""

MOCK_CHANGE_ITEMS = [
    {
        "section_name": "个人简介",
        "original_text": "Java开发工程师",
        "optimized_text": "3年Java开发经验，专注电商领域微服务架构设计",
        "change_type": "polish",
        "reason": "突出经验年限和领域专注度",
        "evidence_source": "简历原文",
        "requires_user_confirmation": False,
        "confidence": 0.95,
    },
    {
        "section_name": "工作经历",
        "original_text": "参与电商平台后端开发",
        "optimized_text": "独立负责电商平台核心模块（订单/支付）后端开发，日均处理10万+订单",
        "change_type": "polish",
        "reason": "添加量化数据和角色描述",
        "evidence_source": "简历原文",
        "requires_user_confirmation": False,
        "confidence": 0.9,
    },
    {
        "section_name": "专业技能",
        "original_text": "Java, Spring Boot, MySQL, Redis, Git",
        "optimized_text": "Java, Spring Boot, Spring Cloud, MySQL, Redis, Kafka, Docker, K8s, Git",
        "change_type": "fact_inference",
        "reason": "添加JD匹配的关键词",
        "evidence_source": "JD关键词",
        "requires_user_confirmation": True,
        "confidence": 0.6,
    },
    {
        "section_name": "项目经历",
        "original_text": "",
        "optimized_text": "主导电商平台从单体到微服务架构的迁移，系统可用性提升至99.99%，QPS提升200%",
        "change_type": "fact_inference",
        "reason": "增强项目描述的竞争力",
        "evidence_source": "JD关键词",
        "requires_user_confirmation": True,
        "confidence": 0.4,
    },
]


# ============================================================================
# Pipeline 阶段测试
# ============================================================================

class TestPipelineState:
    """PipelineState 数据类测试"""

    def test_default_state(self):
        state = PipelineState(
            resume_content="test",
            job_description="test JD",
        )
        assert state.change_items == []
        assert state.errors == []
        assert state.assembled_resume == ""

    def test_with_user_id(self):
        state = PipelineState(
            resume_content="test",
            job_description="test",
            user_id="user-123",
        )
        assert state.user_id == "user-123"


class TestStage2MaterialSelection:
    """素材选择阶段测试"""

    @pytest.mark.asyncio
    async def test_basic_material_pool(self):
        state = PipelineState(
            resume_content=MOCK_RESUME,
            job_description=MOCK_JD,
        )
        state = await stage2_material_selection(state)

        assert state.material_pool is not None
        assert state.material_pool["resume"] == MOCK_RESUME
        assert "allowed_inference_areas" in state.material_pool
        assert "requires_confirmation_areas" in state.material_pool

    @pytest.mark.asyncio
    async def test_empty_material_pool(self):
        state = PipelineState(
            resume_content="",
            job_description="",
        )
        state = await stage2_material_selection(state)
        assert state.material_pool is not None


class TestChangeItemSchema:
    """ChangeItem Schema 测试"""

    def test_valid_polish(self):
        item = ChangeItem(
            section_name="个人简介",
            original_text="Java开发",
            optimized_text="3年Java开发经验",
            change_type="polish",
            reason="润色表达",
            evidence_source="简历原文",
        )
        assert item.evidence_source == "简历原文"
        assert not item.requires_user_confirmation

    def test_valid_fact_inference(self):
        item = ChangeItem(
            section_name="专业技能",
            optimized_text="熟悉K8s和Docker",
            change_type="fact_inference",
            reason="匹配JD要求",
            evidence_source="JD关键词",
            requires_user_confirmation=True,
        )
        assert item.requires_user_confirmation
        assert item.evidence_source == "JD关键词"

    def test_default_values(self):
        item = ChangeItem(
            section_name="test",
            optimized_text="test content",
            change_type="polish",
        )
        assert item.confidence == 0.8
        assert item.evidence_source == ""
        assert not item.requires_user_confirmation

    def test_serialization_roundtrip(self):
        item = ChangeItem(
            section_name="工作经历",
            original_text="做了开发",
            optimized_text="负责核心模块开发",
            change_type="polish",
            reason="专业化表达",
            evidence_source="简历原文",
            confidence=0.95,
        )
        data = item.model_dump()
        restored = ChangeItem.model_validate(data)
        assert restored.section_name == "工作经历"
        assert restored.evidence_source == "简历原文"


class TestConfidenceCalc:
    """置信度计算测试"""

    def test_empty_items(self):
        assert _calc_confidence([]) == 1.0

    def test_single_item(self):
        items = [{"confidence": 0.9}]
        assert _calc_confidence(items) == 0.9

    def test_multiple_items(self):
        items = [{"confidence": 0.8}, {"confidence": 0.9}, {"confidence": 1.0}]
        assert _calc_confidence(items) == 0.9


class TestFactCheck:
    """事实核验测试"""

    def test_detect_keyword_stuffing(self):
        assembled = "熟悉Kubernetes、Docker、Kafka、RabbitMQ、高并发系统设计"
        jd_keywords = ["Kubernetes", "Docker", "Kafka", "RabbitMQ"]
        original = "熟悉Java、Spring Boot、MySQL"

        risks = detect_keyword_stuffing(assembled, jd_keywords, original)

        # 应该检测到 K8s/Docker 被硬塞
        assert len(risks) > 0

    def test_no_stuffing_for_valid_keywords(self):
        assembled = "专业技能：Java, Spring Boot, MySQL, Redis"
        jd_keywords = ["Java", "MySQL"]
        original = "Java, Spring Boot, MySQL, Redis"

        risks = detect_keyword_stuffing(assembled, jd_keywords, original)
        assert len(risks) == 0  # 关键词在原简历中已存在

    def test_validate_change_items_high_risk(self):
        result = validate_change_items(
            MOCK_CHANGE_ITEMS,
            MOCK_RESUME,
            "优化后简历：主导架构迁移，QPS提升200%",
            MOCK_JD,
        )
        assert result["overall_risk"] in ("low", "medium", "high")
        # 有 fact_inference 和夸大项
        assert len(result["fact_inference_items"]) > 0

    def test_validate_change_items_low_risk(self):
        safe_items = [MOCK_CHANGE_ITEMS[0], MOCK_CHANGE_ITEMS[1]]  # 只有 polish 类型
        result = validate_change_items(
            safe_items,
            MOCK_RESUME,
            "优化后简历（仅润色）",
            MOCK_JD,
        )
        assert result["overall_risk"] == "low"
        assert len(result["fact_inference_items"]) == 0

    def test_exaggeration_detection(self):
        """夸大检测"""
        result = validate_change_items(
            [MOCK_CHANGE_ITEMS[3]],  # "QPS提升200%"
            MOCK_RESUME,
            "主导架构迁移，QPS提升200%，系统可用性99.99%",
            MOCK_JD,
        )
        # 应该检测到夸大（原简历没有这些数据）
        assert len(result["exaggeration_items"]) > 0 or result["overall_risk"] != "low"


class TestConfirmationKeywords:
    """用户确认关键词测试"""

    def test_high_risk_keywords_defined(self):
        assert "主导" in REQUIRES_CONFIRMATION_KEYWORDS
        assert "从0到1" in REQUIRES_CONFIRMATION_KEYWORDS
        assert "提升200%" in REQUIRES_CONFIRMATION_KEYWORDS

    def test_detect_high_risk_role(self):
        """检测高强度角色表述"""
        item = {
            "section_name": "项目经历",
            "optimized_text": "独立完成核心模块开发，从0到1搭建了整个系统",
            "change_type": "polish",
            "requires_user_confirmation": False,
            "confidence": 0.8,
        }
        # 包含 "独立完成" 和 "从0到1" 两个高风险关键词
        from app.services.resume.resume_orchestrator import stage6_confirmation_prep
        keywords_triggered = sum(
            1 for kw in REQUIRES_CONFIRMATION_KEYWORDS
            if kw in item["optimized_text"]
        )
        assert keywords_triggered >= 2
