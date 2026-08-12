"""岗位导入卡片的确定性清洗和边界校验。"""

from __future__ import annotations

import re
from typing import Any

from integrations.boss.existing_tab_bridge import normalize_company_size_text
from integrations.boss.security import is_allowed_boss_job_url, is_valid_boss_search_card

_INTERNSHIP_MARKERS = ("实习", "实习生", "internship")


def clamp_score(value: Any) -> float | None:
    """把外部卡片分数限制为可展示的 0 到 100 浮点值。"""
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return round(max(0.0, min(score, 100.0)), 1)


def is_internship_card(card: dict[str, Any]) -> bool:
    """识别不允许入库或推荐的实习岗位卡片。"""
    text = " ".join(
        str(card.get(key) or "")
        for key in ("job_title", "title_summary", "job_description")
    ).casefold()
    return any(marker in text for marker in _INTERNSHIP_MARKERS) or bool(
        re.search(r"\bintern\b", text, flags=re.IGNORECASE)
    )


def sanitize_cards(raw_cards: list[Any]) -> list[dict[str, Any]]:
    """裁剪并校验 BOSS DOM 卡片，只保留官方 URL 与有限字段。"""
    cards: list[dict[str, Any]] = []
    for raw_card in raw_cards:
        if not isinstance(raw_card, dict):
            continue
        card = {
            "company_name": str(raw_card.get("company_name") or "").strip()[:200],
            "company_size_text": normalize_company_size_text(raw_card.get("company_size_text")),
            "job_title": str(raw_card.get("job_title") or "").strip()[:200],
            "salary_text": str(raw_card.get("salary_text") or "").strip()[:100],
            "city": str(raw_card.get("city") or "").strip()[:100],
            "title_summary": str(raw_card.get("title_summary") or "").strip()[:300],
            "job_description": str(raw_card.get("job_description") or "").strip()[:3000],
            "source_url": str(raw_card.get("source_url") or "").strip()[:2048],
            "preliminary_match_score": clamp_score(raw_card.get("preliminary_match_score")),
        }
        if (
            is_allowed_boss_job_url(card["source_url"])
            and not is_internship_card(card)
            and is_valid_boss_search_card(card)
        ):
            cards.append(card)
    return cards
