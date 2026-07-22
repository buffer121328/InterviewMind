"""Normalize, deduplicate, and persist captured jobs."""

import logging
from datetime import datetime
from typing import Any, Dict

from .job_deduper import is_duplicate
from .job_normalizer import compute_source_hash, extract_keywords, normalize_company_name, normalize_salary

logger = logging.getLogger(__name__)


async def normalize_and_save_job(
    raw_data: dict,
    user_id: str,
    platform: str,
    source_url: str = "",
    source_text: str = "",
) -> Dict[str, Any]:
    """标准化、去重并保存岗位记录。"""
    from app.infrastructure.db.repositories.jobs.job_capture_repo import get_job_capture_repo

    company_name = normalize_company_name(raw_data.get("company_name", ""))
    job_title = raw_data.get("job_title", "").strip()
    job_description = raw_data.get("job_description", source_text)
    salary_info = normalize_salary(raw_data.get("salary_text", ""))
    city = raw_data.get("city", "").strip()
    keywords = extract_keywords(job_description)

    source_hash = compute_source_hash(
        company_name=company_name,
        job_title=job_title,
        source_url=source_url,
        platform=platform,
    )

    duplicated = await is_duplicate(source_hash, user_id)
    if duplicated:
        return {
            "success": True,
            "message": "该岗位已采集过",
            "is_duplicate": True,
        }

    try:
        repo = get_job_capture_repo()
        job_id = await repo.save_job(
            user_id=user_id,
            job_data={
                "platform": platform,
                "source_url": source_url,
                "source_text": source_text,
                "company_name": company_name,
                "job_title": job_title,
                "job_description": job_description,
                "salary_text": salary_info["text"],
                "salary_min": salary_info["min"],
                "salary_max": salary_info["max"],
                "city": city,
                "tags": keywords,
                "source_hash": source_hash,
                "status": "pending",
                "captured_at": datetime.now().isoformat(),
            },
        )
    except Exception as exc:
        logger.error("[JobCapture] 保存岗位失败: %s", exc)
        return {
            "success": False,
            "message": f"保存岗位失败: {exc}",
            "is_duplicate": False,
        }

    normalized_job = {
        "company_name": company_name,
        "job_title": job_title,
        "job_description": job_description,
        "salary_text": salary_info["text"],
        "salary_min": salary_info["min"],
        "salary_max": salary_info["max"],
        "city": city,
        "tags": keywords,
        "source_hash": source_hash,
    }

    return {
        "success": True,
        "job_id": job_id,
        "normalized_job": normalized_job,
        "is_duplicate": False,
        "message": "岗位采集成功",
    }
