"""
岗位采集服务

岗位来源是用户当前已登录 BOSS 搜索页导入的有限 DOM 岗位卡片。

采集任务只负责校验、过滤实习岗位、标准化并按匹配度排序，返回待入库卡片；
用户确认后由岗位中心「一键入库」调用 import_cards_to_library 真正保存进岗位库。
"""

import logging
from collections.abc import Awaitable, Callable
from hashlib import sha256
from typing import Any, Dict, Optional

from integrations.boss.security import is_allowed_boss_search_url

from .capture import normalization, scoring
from .capture.job_capture_log import JobCaptureTextLog

logger = logging.getLogger(__name__)


# The capture facade owns orchestration only. Bounded context construction,
# card normalization, scoring, and confirmed persistence live in capture/.


async def capture_from_imported_cards(
    user_id: str,
    query: str,
    resume_content: str,
    imported_cards: list[dict[str, Any]],
    source_page_url: str,
    api_config: Optional[dict] = None,
    top_n: int = 5,
    city: Optional[str] = None,
    progress: Callable[[str], Awaitable[None]] | None = None,
    run_id: str | None = None,
) -> Dict[str, Any]:
    """校验现有 BOSS 标签页桥接返回的 DOM 卡片并生成投递资产。

    上游桥接不启动浏览器或复制 profile；本函数不接收 Cookie、HTML 或认证信息，
    只接收最多 20 张经过 URL 白名单约束的有限字段岗位卡片。
    """
    from ai.agents.resume.resume_extract import extract_professional_skills

    resume_content = extract_professional_skills(resume_content).content
    capture_log = JobCaptureTextLog(run_id or "untracked")
    top_n = max(1, min(int(top_n), 20))

    async def mark(stage: str, message: str) -> None:
        """同步更新 AgentRun 阶段与脱敏 TXT 日志。"""
        if progress is not None:
            await progress(stage)
        await capture_log.write(message)

    if not api_config:
        await capture_log.write("导入失败：缺少模型配置")
        return {
            "success": False,
            "total": 0,
            "jobs": [],
            "message": "未检测到 API 配置。请在请求中传入 api_config。",
        }
    if not is_allowed_boss_search_url(source_page_url):
        await capture_log.write("导入失败：来源不是 BOSS 官方岗位搜索页")
        return {
            "success": False,
            "total": 0,
            "jobs": [],
            "message": "仅允许导入 BOSS 官方岗位搜索页。",
        }

    query_fingerprint = sha256(query.encode("utf-8")).hexdigest()[:16]
    logger.info(
        "[JobCapture] 当前页 DOM 导入启动: user=%s query_fingerprint=%s candidates=%s top_n=%s",
        user_id,
        query_fingerprint,
        min(len(imported_cards), 20),
        top_n,
    )
    await mark("validating_import", "正在校验当前 BOSS 页面导入的岗位卡片")

    raw_cards = imported_cards[:20]
    cards = normalization.sanitize_cards(raw_cards)

    rejected_cards = len(raw_cards) - len(cards)
    if rejected_cards:
        await capture_log.write(f"已拒绝 {rejected_cards} 张无效、外部或字段不完整的岗位卡片")
    if not cards:
        return {
            "success": False,
            "total": 0,
            "jobs": [],
            "message": "导入内容中没有有效岗位卡片，请回到 BOSS 搜索结果页重新提取。",
        }

    await mark("extracting_jobs", f"已接收并确认 {len(cards)} 张有效岗位卡片")

    # Step 2.5: 用 fast 通道做轻量匹配度打分，按分取前 top_n 个
    await mark("ranking_jobs", "正在按简历匹配度排序岗位")
    if resume_content:
        scored_cards = await scoring.score_job_cards_by_match(
            cards=cards,
            resume_content=resume_content,
            query=query,
            api_config=api_config,
        )
        if scored_cards:
            cards = scored_cards[:top_n]
            logger.info(f"[JobCapture] 按匹配度排序后取前 {len(cards)} 个")
        else:
            cards = cards[:top_n]
    else:
        cards = cards[:top_n]

    # 采集阶段不保存岗位：返回排序后的待入库卡片，
    # 用户确认后在岗位中心「一键入库」只写入岗位库，不调度模型或资产任务。
    results: list = []
    for card in cards:
        company = card.get("company_name", "")
        title = card.get("job_title", "")
        salary = card.get("salary_text", "")
        city_val = card.get("city", "") or (city or "")
        jd_text = card.get("job_description") or card.get("title_summary") or title
        source_url = str(card.get("source_url") or "")
        results.append({
            "job_id": None,
            "pending_import": True,
            "source_url": source_url,
            "company_name": company,
            "company_size_text": card.get("company_size_text", ""),
            "job_title": title,
            "job_description": jd_text,
            "salary_text": salary,
            "city": city_val,
            "match_score": card.get("preliminary_match_score"),
            "custom_resume_id": None,
            "greetings": [],
            "risk_flags": [],
            "asset_run_id": None,
            "asset_status": None,
        })

    await mark("awaiting_import", f"采集完成，{len(results)} 个岗位等待入库确认")
    await capture_log.write(f"采集完成：{len(results)} 个岗位等待入库确认")
    return {
        "success": len(results) > 0,
        "total": len(results),
        "jobs": results,
        "message": f"已采集 {len(results)} 个岗位，等待入库确认",
    }
