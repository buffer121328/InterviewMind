"""用户确认后的岗位卡片确定性入库。"""

from __future__ import annotations

import logging
from typing import Any

from ai.workflows.jobs.capture.job_capture_persistence import normalize_and_save_job
from ai.workflows.jobs.capture.normalization import sanitize_cards

logger = logging.getLogger(__name__)


async def import_cards_to_library(
    user_id: str,
    cards: list[dict[str, Any]],
    city: str | None = None,
) -> dict[str, Any]:
    """在 owner 范围内保存确认卡片，不启动模型、AgentRun 或后台任务。"""
    valid_cards = sanitize_cards(cards)
    if not valid_cards:
        return {
            "success": False,
            "total": 0,
            "jobs": [],
            "duplicates": 0,
            "failed": [],
            "message": "入库内容中没有有效岗位卡片",
        }
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    duplicates = 0
    for index, card in enumerate(valid_cards, 1):
        company = card.get("company_name", "")
        title = card.get("job_title", "")
        salary = card.get("salary_text", "")
        city_value = card.get("city", "") or (city or "")
        job_description = card.get("job_description") or card.get("title_summary") or title
        source_url = str(card.get("source_url") or "")
        match_score = card.get("preliminary_match_score")
        logger.info("[JobCapture] 确定性入库 [%s/%s]: %s - %s", index, len(valid_cards), company, title)
        try:
            captured = await normalize_and_save_job(
                {**card, "city": city_value, "preliminary_match_score": match_score},
                user_id,
                "boss",
                source_url=source_url,
                source_text=job_description,
            )
        except Exception as exc:  # noqa: BLE001 - return per-card failure details.
            logger.warning("[JobCapture] 卡片 %s 入库失败: %s", index, type(exc).__name__)
            failures.append({"company_name": company, "job_title": title, "reason": str(exc), "source_url": source_url})
            continue
        if not captured.get("success"):
            failures.append({"company_name": company, "job_title": title, "reason": captured.get("message", ""), "source_url": source_url})
            continue
        raw_job_id = captured.get("job_id")
        if not isinstance(raw_job_id, (int, str)):
            failures.append({"company_name": company, "job_title": title, "reason": "岗位保存返回了无效 ID", "source_url": source_url})
            continue
        if captured.get("is_duplicate"):
            duplicates += 1
        results.append(
            {
                "job_id": int(raw_job_id),
                "source_url": source_url,
                "company_name": company,
                "company_size_text": card.get("company_size_text", ""),
                "job_title": title,
                "job_description": job_description,
                "salary_text": salary,
                "city": city_value,
                "match_score": match_score,
                "custom_resume_id": None,
                "risk_flags": [],
                "asset_run_id": None,
                "asset_status": None,
            }
        )
    message = f"共入库 {len(results)} 个岗位"
    if duplicates:
        message += f"，其中 {duplicates} 个已存在并复用"
    if failures:
        message += f"，{len(failures)} 个失败"
    return {
        "success": len(results) > 0,
        "total": len(results),
        "duplicates": duplicates,
        "jobs": results,
        "failed": failures,
        "message": message,
    }
