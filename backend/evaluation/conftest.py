"""
共享 fixtures：evaluation 测试套件
提供统一的 mock 配置、状态构建器和数据集加载器。
"""

import json
import os
from pathlib import Path
from typing import List, Optional, Literal
from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# DeepEval assert_test 默认使用异步执行路径，会在 pytest-asyncio 的
# 混合测试集中触发 asyncio.get_event_loop() 的弃用告警，甚至遗留未关闭
# event loop。评测用例里的指标均可同步执行；集中把默认值固定为
# run_async=False，单个测试仍可显式覆盖。
# ---------------------------------------------------------------------------

def _patch_deepeval_assert_test_default_sync() -> None:
    try:
        import deepeval
    except Exception:
        return

    original = deepeval.assert_test
    if getattr(original, "_agent_interview_sync_default", False):
        return

    def assert_test_sync_default(*args, run_async: bool = False, **kwargs):
        result = original(*args, run_async=run_async, **kwargs)
        try:
            from observability.evaluation_reporting import report_deepeval_assertion

            test_case = args[0] if args else kwargs.get("test_case")
            metrics = args[1] if len(args) > 1 else kwargs.get("metrics") or []
            report_deepeval_assertion(test_case=test_case, metrics=metrics)
        except Exception:
            # Evaluation reporting must never affect DeepEval assertions.
            pass
        return result

    assert_test_sync_default._agent_interview_sync_default = True
    deepeval.assert_test = assert_test_sync_default


_patch_deepeval_assert_test_default_sync()


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
    Patch ai.llm.llms.get_llm_for_request，返回 AsyncMock。
    用法: def test_xxx(mock_llm): ...
    """
    with patch("ai.llm.llms.get_llm_for_request", new_callable=AsyncMock) as _mock:
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
# 数据集目录常量
# ---------------------------------------------------------------------------

_DATASETS_DIR = Path(__file__).resolve().parent / "datasets"


def _load_json(filename: str):
    """从 evaluation/datasets/ 加载 JSON 文件；文件不存在时返回空列表并发出警告。"""
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
    """加载 evaluation/datasets/interview_golden.json 中的 golden-case 列表。"""
    return _load_json("interview_golden.json")


# ---------------------------------------------------------------------------
# 7. golden_resume_cases fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def golden_resume_cases():
    """加载 evaluation/datasets/resume_golden.json 中的 golden-case 列表。"""
    return _load_json("resume_golden.json")


# ---------------------------------------------------------------------------
# 8. scoring_benchmarks fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def scoring_benchmarks():
    """加载 evaluation/datasets/scoring_benchmarks.json 中的评分基准数据。"""
    return _load_json("scoring_benchmarks.json")


def pytest_collection_modifyitems(items):
    """无评审模型凭据时，只跳过显式标记的 LLM-as-Judge 评测。"""
    if os.getenv("OPENAI_API_KEY"):
        return

    skip_llm_eval = pytest.mark.skip(
        reason="未设置 OPENAI_API_KEY，跳过 LLM-as-Judge 评测"
    )
    for item in items:
        if "llm" in item.keywords and "eval" in item.keywords:
            item.add_marker(skip_llm_eval)
