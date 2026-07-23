"""Tests for the DeepEval assert_test reporting hook installed by eval conftest."""

import importlib.util
import sys
import types
from pathlib import Path


def test_deepeval_assert_test_patch_reports_successful_metrics(monkeypatch):
    calls = []

    fake_deepeval = types.ModuleType("deepeval")

    def original_assert_test(*args, run_async=True, **kwargs):
        calls.append((args, run_async, kwargs))
        return "ok"

    fake_deepeval.assert_test = original_assert_test
    monkeypatch.setitem(sys.modules, "deepeval", fake_deepeval)

    reported = []
    monkeypatch.setattr(
        "observability.evaluation_reporting.report_deepeval_assertion",
        lambda **kwargs: reported.append(kwargs) or {"attempted": 1, "reported": 1, "failed": 0},
    )

    conftest_path = Path(__file__).resolve().parents[1] / "deepeval_tests" / "conftest.py"
    spec = importlib.util.spec_from_file_location("_agent_interview_eval_conftest_for_test", conftest_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    test_case = object()
    metrics = [object()]
    assert fake_deepeval.assert_test(test_case, metrics) == "ok"

    assert calls[0][1] is False
    assert reported == [{"test_case": test_case, "metrics": metrics}]
