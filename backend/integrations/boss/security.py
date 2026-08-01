"""BOSS 页面导入共享的无状态安全规则。"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import ParseResult, urlparse

_BOSS_SEARCH_PATHS = {"/web/geek/job", "/web/geek/jobs"}
_BOSS_JOB_PATH = re.compile(r"/job_detail/[A-Za-z0-9_-]+\.html")
_INVALID_SEARCH_CARD_TITLES = {
    "职位搜索",
    "搜索职位",
    "热门职位",
    "全部职位",
    "boss直聘",
}


def _parse_allowed_boss_url(value: str) -> ParseResult | None:
    """解析 BOSS URL，并拒绝用户信息、非标准端口和畸形 authority。"""

    try:
        parsed = urlparse(value)
        hostname = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or not (hostname == "zhipin.com" or hostname.endswith(".zhipin.com"))
    ):
        return None
    return parsed


def is_allowed_boss_origin_url(value: str) -> bool:
    """只允许访问 BOSS 直聘官方 HTTPS 域名。"""

    return _parse_allowed_boss_url(value) is not None


def is_allowed_boss_search_url(value: str) -> bool:
    """只接受用户当前打开的 BOSS 官方岗位搜索页。"""

    parsed = _parse_allowed_boss_url(value)
    return (
        parsed is not None
        and parsed.path.rstrip("/").lower() in _BOSS_SEARCH_PATHS
    )


def is_allowed_boss_job_url(value: str) -> bool:
    """只接受 BOSS 官方岗位详情链接，拒绝导航和外部伪链接。"""

    parsed = _parse_allowed_boss_url(value)
    return parsed is not None and _BOSS_JOB_PATH.fullmatch(parsed.path) is not None


def boss_job_url_matches_expected(actual_url: str, expected_url: str) -> bool:
    """确认导航后的官方页面仍是同一岗位，阻断外部或站内其他岗位重定向。"""

    if not is_allowed_boss_job_url(actual_url) or not is_allowed_boss_job_url(expected_url):
        return False
    return urlparse(actual_url).path == urlparse(expected_url).path


def is_valid_boss_search_card(card: dict[str, Any]) -> bool:
    """拒绝导航卡片和字段不完整的岗位卡片，避免无效数据进入持久化。"""

    title = str(card.get("job_title", "") or "").strip()
    company = str(card.get("company_name", "") or "").strip()
    salary = str(card.get("salary_text", "") or "").strip()
    description = str(
        card.get("job_description")
        or card.get("title_summary")
        or ""
    ).strip()
    source_url = str(card.get("source_url", "") or "").strip()
    if not title or title.casefold() in _INVALID_SEARCH_CARD_TITLES:
        return False
    if source_url and not is_allowed_boss_job_url(source_url):
        return False
    return bool((company or salary) and len(description) >= 8)
