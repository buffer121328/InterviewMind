"""数据库与 checkpoint 事实来源优先级测试。"""

from app.infrastructure.memory.memory import FACT_SOURCE_PRIORITY, fact_source_for


def test_database_is_authoritative_for_business_facts():
    assert FACT_SOURCE_PRIORITY == ("database", "checkpoint")
    assert fact_source_for("business_result") == "database"
    assert fact_source_for("agent_run_status") == "database"
    assert fact_source_for("recoverable_runtime_state") == "checkpoint"
    assert fact_source_for("unknown") == "database"
