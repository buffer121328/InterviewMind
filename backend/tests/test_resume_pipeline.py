"""
简历 6 阶段 Pipeline 测试

验证：
- 各阶段输出 Schema 正确性
- ChangeItem 标准化字段
- 证据来源追踪
- 事实核验策略
"""

from contextlib import asynccontextmanager

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import app.agents.resume.resume_orchestrator as orchestrator

from app.agents.resume.resume_orchestrator import (
    PipelineState,
    run_pipeline,
    stage1_jd_analysis,
    stage2_material_selection,
    stage3_custom_rewrite,
    stage4_assemble,
    stage5_fact_check,
    stage5_quality_judge,
    stage6_confirmation_prep,
    _calc_confidence,
)
from app.agents.resume.resume_fact_policy import (
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
        assert state.trace == []

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


class TestQualityJudge:
    """质量评审测试"""

    @pytest.mark.asyncio
    async def test_quality_judge_passes_low_risk_result(self):
        state = PipelineState(resume_content=MOCK_RESUME, job_description=MOCK_JD)
        state.change_items = [MOCK_CHANGE_ITEMS[0]]
        state.assembled_resume = "3年Java开发经验，负责电商平台后端开发"
        state.fact_check_result = {
            "overall_risk": "low",
            "risk_flags": [],
            "keyword_stuffing_risks": [],
            "fact_inference_items": [],
            "exaggeration_items": [],
            "total_risks": 0,
        }

        state = await stage5_quality_judge(state)

        assert state.judge_result["passed"] is True
        assert state.judge_result["decision"] == "pass"
        assert state.judge_result["score"] >= 70

    @pytest.mark.asyncio
    async def test_quality_judge_builds_retry_guidance(self):
        state = PipelineState(resume_content=MOCK_RESUME, job_description=MOCK_JD)
        state.jd_analysis = {"missing_keywords": ["Kubernetes", "Kafka"]}
        state.change_items = []
        state.assembled_resume = ""
        state.fact_check_result = {
            "overall_risk": "high",
            "risk_flags": [{}, {}, {}],
            "keyword_stuffing_risks": [{"keyword": "Kubernetes"}],
            "fact_inference_items": [{"section_name": "专业技能"}],
            "exaggeration_items": [{"description": "过度夸大百分比"}],
            "total_risks": 3,
        }

        state = await stage5_quality_judge(state)

        assert state.judge_result["passed"] is False
        assert state.judge_result["decision"] == "retry"
        assert "硬塞" in state.judge_result["retry_guidance"]
        assert "夸大" in state.judge_result["retry_guidance"]


class TestRunPipelineRetry:
    """一次定向返工测试"""

    @pytest.mark.asyncio
    async def test_run_pipeline_retries_once_when_first_judge_fails(self, monkeypatch):
        rewrite_calls = []

        async def fake_stage1(state):
            state.jd_analysis = {"match_score": 62, "missing_keywords": ["Kubernetes"]}
            return state

        async def fake_stage2(state, session_ids=None, include_profile=False):
            state.material_pool = {"resume": state.resume_content, "interview_conversations": [], "profile": None}
            return state

        async def fake_stage3(state):
            rewrite_calls.append(state.retry_count)
            if state.retry_count == 0:
                state.change_items = [{
                    "section_name": "项目经历",
                    "optimized_text": "主导系统迁移，QPS提升200%",
                    "change_type": "fact_inference",
                    "requires_user_confirmation": True,
                    "confidence": 0.4,
                }]
            else:
                state.change_items = [{
                    "section_name": "工作经历",
                    "optimized_text": "负责订单模块后端开发与优化",
                    "change_type": "polish",
                    "requires_user_confirmation": False,
                    "confidence": 0.92,
                }]
            return state

        async def fake_stage4(state):
            state.assembled_resume = (
                "主导系统迁移，QPS提升200%"
                if state.retry_count == 0
                else "负责订单模块后端开发与优化"
            )
            return state

        async def fake_stage5(state):
            if state.retry_count == 0:
                state.fact_check_result = {
                    "overall_risk": "high",
                    "risk_flags": [{}, {}],
                    "keyword_stuffing_risks": [],
                    "fact_inference_items": [{"section_name": "项目经历"}],
                    "exaggeration_items": [{"description": "过度夸大百分比"}],
                    "total_risks": 2,
                }
            else:
                state.fact_check_result = {
                    "overall_risk": "low",
                    "risk_flags": [],
                    "keyword_stuffing_risks": [],
                    "fact_inference_items": [],
                    "exaggeration_items": [],
                    "total_risks": 0,
                }
            return state

        async def fake_stage6(state):
            state.confirmation_items = []
            return state

        monkeypatch.setattr(orchestrator, "stage1_jd_analysis", fake_stage1)
        monkeypatch.setattr(orchestrator, "stage2_material_selection", fake_stage2)
        monkeypatch.setattr(orchestrator, "stage3_custom_rewrite", fake_stage3)
        monkeypatch.setattr(orchestrator, "stage4_assemble", fake_stage4)
        monkeypatch.setattr(orchestrator, "stage5_fact_check", fake_stage5)
        monkeypatch.setattr(orchestrator, "stage6_confirmation_prep", fake_stage6)

        result = await run_pipeline(
            resume_content=MOCK_RESUME,
            job_description=MOCK_JD,
            user_id="user-1",
        )

        assert rewrite_calls == [0, 1]
        assert result["rewrite_attempts"] == 2
        assert result["judge_result"]["passed"] is True
        assert any(item["step"] == "stage5_targeted_retry" for item in result["trace"])

    @pytest.mark.asyncio
    async def test_run_pipeline_creates_resume_root_observation_with_summary_only(self, monkeypatch):
        observed = []

        class FakeObservation:
            def set_output(self, output):
                observed[0]["output"] = output

        @asynccontextmanager
        async def fake_agent_observation(**kwargs):
            observed.append(kwargs)
            yield FakeObservation()

        async def fake_stage1(state):
            state.jd_analysis = {"match_score": 80}
            return state

        async def fake_stage2(state, session_ids=None, include_profile=False):
            state.material_pool = {"resume": state.resume_content}
            return state

        async def fake_stage3(state):
            state.change_items = []
            return state

        async def fake_stage4(state):
            state.assembled_resume = state.resume_content
            return state

        async def fake_stage5(state):
            state.fact_check_result = {"overall_risk": "low", "total_risks": 0}
            return state

        async def fake_quality_judge(state):
            state.judge_result = {"passed": True, "decision": "accept"}
            return state

        async def fake_stage6(state):
            state.confirmation_items = []
            return state

        monkeypatch.setattr(orchestrator, "agent_observation", fake_agent_observation, raising=False)
        monkeypatch.setattr(orchestrator, "stage1_jd_analysis", fake_stage1)
        monkeypatch.setattr(orchestrator, "stage2_material_selection", fake_stage2)
        monkeypatch.setattr(orchestrator, "stage3_custom_rewrite", fake_stage3)
        monkeypatch.setattr(orchestrator, "stage4_assemble", fake_stage4)
        monkeypatch.setattr(orchestrator, "stage5_fact_check", fake_stage5)
        monkeypatch.setattr(orchestrator, "stage5_quality_judge", fake_quality_judge)
        monkeypatch.setattr(orchestrator, "stage6_confirmation_prep", fake_stage6)

        await run_pipeline(MOCK_RESUME, MOCK_JD, "user-1", session_ids=["s-1"])

        assert observed[0]["name"] == "resume-pipeline"
        assert observed[0]["agent_type"] == "resume"
        assert observed[0]["user_id"] == "user-1"
        assert observed[0]["input_payload"] == {
            "resume_length": len(MOCK_RESUME),
            "job_description_length": len(MOCK_JD),
            "session_count": 1,
            "include_profile": False,
        }
        assert observed[0]["output"] == {
            "changes": 0,
            "confirmations": 0,
            "rewrite_attempts": 1,
            "has_errors": False,
        }


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
        from app.agents.resume.resume_orchestrator import stage6_confirmation_prep
        keywords_triggered = sum(
            1 for kw in REQUIRES_CONFIRMATION_KEYWORDS
            if kw in item["optimized_text"]
        )
        assert keywords_triggered >= 2
