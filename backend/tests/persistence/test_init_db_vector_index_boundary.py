"""init_db 与 Alembic 向量索引结构的职责边界回归测试。"""

from pathlib import Path

_SOURCE = Path(__file__).resolve().parents[2] / "app" / "db" / "models" / "base.py"


def test_init_db_does_not_recreate_retired_single_dimension_hnsw_index() -> None:
    """开发启动路径不得引用迁移 16 已淘汰的旧单维度 HNSW 索引。"""

    source = _SOURCE.read_text(encoding="utf-8")
    assert "idx_rag_chunks_embedding_hnsw" not in source.replace(
        "idx_rag_chunks_embedding_hnsw_", ""
    )
    # trgm/gin 与基线迁移定义一致，保留为开发便利。
    assert "idx_rag_chunks_content_trgm" in source
    assert "idx_rag_chunks_metadata_gin" in source


def test_compose_keeps_migration_first_deployment_defaults() -> None:
    """全容器部署保持 AUTO_CREATE_TABLES=false 且 migrate 先于 backend/worker。"""

    compose = (Path(__file__).resolve().parents[2] / ".." / "docker-compose.yml").resolve()
    text = compose.read_text(encoding="utf-8")
    assert 'AUTO_CREATE_TABLES: "false"' in text
    backend_block = text.split("  backend:")[1].split("  worker:")[0]
    worker_block = text.split("  worker:")[1].split("  frontend:")[0]
    for block in (backend_block, worker_block):
        assert "migrate:" in block
        assert "service_completed_successfully" in block
