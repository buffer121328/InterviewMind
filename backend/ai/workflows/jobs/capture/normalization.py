"""岗位导入卡片的确定性清洗和边界校验。"""

from __future__ import annotations

import re
from typing import Any

from integrations.boss.existing_tab_bridge import normalize_company_size_text
from integrations.boss.security import is_allowed_boss_job_url, is_valid_boss_search_card

_INTERNSHIP_MARKERS = ("实习", "实习生", "internship")
_EXPERIENCE_TEXT_KEYS = ("job_title", "title_summary", "job_description")
_FULLWIDTH_EXPERIENCE_TRANSLATION = str.maketrans("０１２３４５６７８９－～", "0123456789-~")
_EXPLICIT_EXPERIENCE_PATTERNS = (
    # BOSS 搜索卡片常以“1-3年 本科”简写经验。限制到一至两位数，避免把年份误认为经验。
    re.compile(
        r"(?:^|[\s:：,，;；])(?:[1-9]\d?|[一二三四五六七八九十]+)"
        r"(?:\s*[-~～—至到]\s*(?:[1-9]\d?|[一二三四五六七八九十]+))?"
        r"\s*年(?:\s*(?:及以上|以上))?(?=(?:\s|$|[，,；；。]))"
    ),
    # “至少一年”“不少于 1 年”等明确的最低年限要求。
    re.compile(
        r"(?:至少|不少于|不低于|满)\s*(?:[1-9]\d?|[一二三四五六七八九十]+)\s*年"
    ),
    # 对既往工作经验的硬性要求；“优先”不是硬条件，交由下面的判定排除。
    re.compile(
        r"(?:有|具备|具有|拥有|要求|需要|(?<!无)需|须)"
        r"[^。；\n]{0,16}?(?:(?:相关|行业|实际|岗位|项目)?(?:工作|从业|开发|运营)?经验)"
    ),
    re.compile(
        r"(?:任职要求|岗位要求|职位要求)[^。；\n]{0,48}?"
        r"(?:有|具备|具有|拥有)[^。；\n]{0,12}?"
        r"(?:(?:相关|行业|实际|岗位|项目)?(?:工作|从业|开发|运营)?经验)"
    ),
)


def clamp_score(value: Any) -> float | None:
    """把外部卡片分数限制为可展示的 0 到 100 浮点值。

    Args:
        value: 外部传入的原始分数，无法解析为数字时返回 None。
    """
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return round(max(0.0, min(score, 100.0)), 1)


def is_internship_card(card: dict[str, Any]) -> bool:
    """识别不允许入库或推荐的实习岗位卡片。

    Args:
        card: 单张岗位卡片。
    """
    text = " ".join(
        str(card.get(key) or "")
        for key in ("job_title", "title_summary", "job_description")
    ).casefold()
    return any(marker in text for marker in _INTERNSHIP_MARKERS) or bool(
        re.search(r"\bintern\b", text, flags=re.IGNORECASE)
    )


def _experience_requirement_text(card: dict[str, Any]) -> str:
    """汇总已采集的有限 JD 字段，用于无经验资格校验。

    Args:
        card: 单张岗位卡片。
    """
    return " ".join(str(card.get(key) or "") for key in _EXPERIENCE_TEXT_KEYS)


def has_explicit_experience_requirement(card: dict[str, Any]) -> bool:
    """只识别 JD 中明确的既往经验硬条件，不推断模糊表达。

    Args:
        card: 卡片数据。
    """
    text = re.sub(r"\s+", " ", _experience_requirement_text(card)).translate(
        _FULLWIDTH_EXPERIENCE_TRANSLATION
    )
    if not text:
        return False
    for pattern in _EXPLICIT_EXPERIENCE_PATTERNS:
        match = pattern.search(text)
        if match is None:
            continue
        # “有相关工作经验优先”不是硬资格条件；其余明确措辞才排除。
        trailing_text = text[match.end():match.end() + 8]
        if "优先" not in trailing_text:
            return True
    return False


def filter_cards_for_experience(
    cards: list[dict[str, Any]],
    experience: str,
) -> tuple[list[dict[str, Any]], int]:
    """应用无经验的确定性资格边界，并返回被排除的卡片数量。

    Args:
        cards: 卡片列表。
        experience: 经验描述。
    """
    if experience != "no_experience":
        return cards, 0
    eligible_cards = [card for card in cards if not has_explicit_experience_requirement(card)]
    return eligible_cards, len(cards) - len(eligible_cards)


def sanitize_cards(raw_cards: list[Any]) -> list[dict[str, Any]]:
    """裁剪并校验 BOSS DOM 卡片，只保留官方 URL 与有限字段。

    Args:
        raw_cards: 传入的 raw_cards 值。
    """
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
