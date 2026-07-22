"""pytest 标记注册，支撑真实基础设施测试分组运行。"""

from pathlib import Path


def test_used_pytest_markers_are_registered():
    pytest_ini = Path(__file__).resolve().parents[1] / "pytest.ini"
    content = pytest_ini.read_text()

    for marker in [
        "eval",
        "fast",
        "llm",
        "regression",
        "integration",
        "contract",
        "requires_postgres",
        "requires_redis",
        "requires_dramatiq",
    ]:
        assert f"    {marker}:" in content
