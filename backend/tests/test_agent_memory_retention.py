"""长期记忆有效期和删除同步契约测试。"""

from app.infrastructure.memory.service import _retention_metadata


def test_retention_metadata_has_expiry_and_delete_policy(monkeypatch):
    monkeypatch.setenv("MEM0_RETENTION_DAYS", "30")

    metadata = _retention_metadata()

    assert metadata["retention_days"] == 30
    assert metadata["expires_at"]
    assert metadata["delete_sync_policy"] == "mem0_delete_by_user_or_expiry"
