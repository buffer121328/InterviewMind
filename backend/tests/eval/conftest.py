"""
共享 fixtures：evaluation 测试套件
提供统一的 mock 配置、状态构建器和数据集加载器。
"""

import json
from pathlib import Path
from typing import List, Optional, Literal
from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# 1. 固定的测试 API 配置
# ---------------------------------------------------------------------------

TEST_API_CONFIG: dict = {
    "smart": {
        "base_url": "https://test.openai.com/v1",
        "api_key": "test-key-smart",
        "model": "gpt-4o-mini",
    },
    "fast": {
        "base_url": "https://test.openai.com/v1",
        "api_key": "test-key-fast",
        "model": "gpt-4o-mini",
    },
    "general": {
        "base_url": "https://test.openai.com/v1",
        "api_key": "test-key-general",
        "model": "gpt-4o-mini",
    },
}


# ---------------------------------------------------------------------------
# 2. mock_api_config fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_api_config() -> dict:
    """返回固定的测试 API 配置。"""
    return TEST_API_CONFIG


# ---------------------------------------------------------------------------
# 3. mock_llm fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_llm():
    """
    Patch app.services.llms.get_llm_for_request，返回 AsyncMock。
    用法: def test_xxx(mock_llm): ...
    """
    with patch("app.services.llms.get_llm_for_request", new_callable=AsyncMock) as _mock:
        yield _mock


# ---------------------------------------------------------------------------
# 4. build_test_state — 构造 InterviewState dict
# ---------------------------------------------------------------------------

def build_test_state(**overrides) -> dict:
    """
    构造一个合法的 InterviewState 字典，所有字段都有合理的默认值。
    可通过关键字参数覆盖任意字段。

    Returns:
        dict: 可直接传给 graph 节点 / 路由函数的 state dict。
    """
    base = {
        "messages": [],
        "resume_context": "测试简历内容",
        "job_description": "测试岗位描述",
        "company_info": "",
        "mode": "mock",
        "session_id": "test-session-001",
        "interview_plan": [],
        "current_question_index": 0,
        "max_questions": 5,
        "question_count": 0,
        "follow_up_count": 0,
        "turn_phase": "opening",
        "current_sub_question": None,
        "max_follow_ups": 2,
        "api_config": TEST_API_CONFIG,
        "round_index": 1,
        "round_type": "tech_initial",
        "memory_context": "",
        "memory_items": [],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 5. build_resume_test_state — 构造 ResumeOptimizerState dict
# ---------------------------------------------------------------------------

def build_resume_test_state(**overrides) -> dict:
    """
    构造一个合法的 ResumeOptimizerState 字典，所有字段都有合理的默认值。
    可通过关键字参数覆盖任意字段。

    Returns:
        dict: 可直接传给简历优化 graph 节点的 state dict。
    """
    base = {
        "resume_content": "测试简历内容",
        "job_description": "测试岗位描述",
        "session_ids": [],
        "include_overall_profile": False,
        "api_config": TEST_API_CONFIG,
        "user_id": "test_user",
        "interview_conversations": [],
        "overall_profile": None,
        "match_analysis": None,
        "content_suggestions": None,
        "hr_review": None,
        "moderator_summary": None,
        "reflection": None,
        "refined_result": None,
        "final_result": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 数据集目录常量
# ---------------------------------------------------------------------------

_DATASETS_DIR = Path(__file__).resolve().parent.parent / "datasets"


def _load_json(filename: str):
    """从 tests/datasets/ 加载 JSON 文件；文件不存在时返回空列表并发出警告。"""
    path = _DATASETS_DIR / filename
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 6. golden_interview_cases fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def golden_interview_cases():
    """加载 tests/datasets/interview_golden.json 中的 golden-case 列表。"""
    return _load_json("interview_golden.json")


# ---------------------------------------------------------------------------
# 7. golden_resume_cases fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def golden_resume_cases():
    """加载 tests/datasets/resume_golden.json 中的 golden-case 列表。"""
    return _load_json("resume_golden.json")


# ---------------------------------------------------------------------------
# 8. scoring_benchmarks fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def scoring_benchmarks():
    """加载 tests/datasets/scoring_benchmarks.json 中的评分基准数据。"""
    return _load_json("scoring_benchmarks.json")
