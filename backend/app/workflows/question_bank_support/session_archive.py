"""向后兼容：问答归档纯转换已下沉至 Repository 同层 mapper。"""

from app.infrastructure.db.repositories.interview.archive_mapper import ArchivedTurn, build_archived_turns

__all__ = ["ArchivedTurn", "build_archived_turns"]
