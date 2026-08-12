"""
岗位采集服务

岗位来源是用户当前已登录 BOSS 搜索页导入的有限 DOM 岗位卡片。

采集任务只负责校验、过滤实习岗位、标准化并按匹配度排序，返回待入库卡片；
用户确认后由岗位中心「一键入库」调用 import_cards_to_library 真正保存进岗位库。
"""

import logging
import re
from collections.abc import Awaitable, Callable
from hashlib import sha256
from typing import Any, Dict, Optional

from ai.runtime.context.assembler import (
    AssembledContext,
    ContextAssembler,
    ContextSource,
)
from ai.runtime.execution.deadlines import TaskDeadline
from app.config import get_settings
from integrations.boss.existing_tab_bridge import normalize_company_size_text
from integrations.boss.security import (
    is_allowed_boss_job_url,
    is_allowed_boss_search_url,
    is_valid_boss_search_card,
)

from .capture.job_capture_log import JobCaptureTextLog
from .capture.job_capture_persistence import normalize_and_save_job as _normalize_and_save

logger = logging.getLogger(__name__)


def _assemble_job_model_context(
    *,
    stage: str,
    sources: list[ContextSource],
    total_model_chars: int,
) -> tuple[AssembledContext, dict[str, Any]]:
    """组装岗位模型上下文相关后端逻辑。"""
    source_budgets = {
        source.name: source.max_chars
        for source in sources
        if source.max_chars is not None
    }
    assembled = ContextAssembler(
        agent_name="job_capture",
        total_model_chars=total_model_chars,
        source_budgets=source_budgets,
        cache_version="2026-07-29.phase6.job_capture.v1",
    ).assemble(sources)
    return assembled, {**assembled.model_event_fields(), "stage": stage}


_INTERNSHIP_MARKERS = ("实习", "实习生", "internship")
def _is_internship_card(card: dict[str, Any]) -> bool:
    """处理岗位服务相关后端逻辑。"""
    text = " ".join(str(card.get(key) or "") for key in (
        "job_title", "title_summary", "job_description",
    )).casefold()
    return any(marker in text for marker in _INTERNSHIP_MARKERS) or bool(
        re.search(r"\bintern\b", text, flags=re.IGNORECASE)
    )


def _clamp_score(value: Any) -> Optional[float]:
    """处理分数相关后端逻辑。"""
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return round(max(0.0, min(score, 100.0)), 1)


def _sanitize_cards(raw_cards: list) -> list[dict[str, Any]]:
    """脱敏岗位服务相关后端逻辑。"""
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
            "preliminary_match_score": _clamp_score(raw_card.get("preliminary_match_score")),
        }
        if not is_allowed_boss_job_url(card["source_url"]):
            continue
        if _is_internship_card(card):
            continue
        if is_valid_boss_search_card(card):
            cards.append(card)
    return cards


async def _score_job_cards_by_match(
    cards: list,
    resume_content: str,
    query: str,
    api_config: Optional[dict] = None,
    deadline: TaskDeadline | None = None,
) -> list:
    """
    用 fast 通道一次性对所有候选岗位做轻量匹配度打分，按分数降序排序。

    这一步不调用 jd_matcher（那个调用太重，会生成详细分析+建议），
    仅让 LLM 一次性对每张卡片输出一个 0-100 的匹配分数。

    Args:
        cards: 已通过当前 BOSS 搜索页 DOM 校验的有限岗位卡片列表
        resume_content: 简历内容
        query: 用户搜索的关键词
        api_config: API 配置

    Returns:
        按匹配度降序的卡片列表，每张卡片新增一个 preliminary_match_score 字段
    """
    import json as _json

    from ai.llm import llms

    if not cards or not resume_content:
        return cards

    from ai.agents.resume.jd_matcher import score_jd_match_fast

    deterministic_scores = {}
    for idx, card in enumerate(cards):
        job_text = " ".join(str(card.get(key) or "") for key in (
            "job_title", "title_summary", "job_description",
        ))
        deterministic_scores[idx] = float(score_jd_match_fast(
            resume_content=resume_content,
            job_description=job_text,
            query=query,
        )["ranking_score"])

    # 构造紧凑的卡片列表（截断 prompt 大小）
    cards_brief = []
    for idx, c in enumerate(cards[:20]):
        cards_brief.append({
            "id": idx,
            "title": c.get("job_title", "")[:50],
            "company": c.get("company_name", "")[:30],
            "salary": c.get("salary_text", ""),
            "city": c.get("city", ""),
            "jd_short": (c.get("job_description") or c.get("title_summary") or "")[:240],
            "keyword_score": deterministic_scores[idx],
        })

    from ai.prompts.jobs import build_job_card_scoring_prompt

    assembled, call_metadata = _assemble_job_model_context(
        stage="job_card_scoring",
        total_model_chars=7000,
        sources=[
            ContextSource(
                name="candidate_resume",
                content=resume_content,
                trusted=True,
                required=True,
                priority=100,
                max_chars=1800,
                truncation_strategy="head_tail",
            ),
            ContextSource(
                name="job_cards",
                content=cards_brief,
                required=True,
                priority=90,
                max_chars=4800,
                truncation_strategy="head_tail",
            ),
            ContextSource(
                name="search_direction",
                content=query,
                trusted=True,
                priority=60,
                max_chars=400,
            ),
        ],
    )
    prompt = build_job_card_scoring_prompt(
        card_count=len(cards_brief),
        scoring_context=assembled.model_context,
    )

    try:
        response = await llms.invoke_text(
            prompt,
            api_config,
            channel="fast",
            deadline=deadline or TaskDeadline(float(get_settings().llm_task_timeout_seconds)),
            call_metadata=call_metadata,
        )
        response_text = response.content if hasattr(response, "content") else str(response)

        # 解析 JSON
        text_strip = response_text.strip()
        if text_strip.startswith("```"):
            text_strip = text_strip.split("```")[1]
            if text_strip.startswith("json"):
                text_strip = text_strip[4:]

        parsed = _json.loads(text_strip)
        scores_list = parsed.get("scores", [])
        score_map = {s.get("id"): s.get("score", 50) for s in scores_list if isinstance(s, dict)}

        # LLM 语义分占 80%，透明关键词重合分占 20%；解析缺项时使用关键词分。
        for idx, c in enumerate(cards):
            keyword_score = deterministic_scores.get(idx, 35.0)
            llm_score = score_map.get(idx)
            if isinstance(llm_score, (int, float)):
                score = float(llm_score) * 0.8 + keyword_score * 0.2
            else:
                score = keyword_score
            c["preliminary_match_score"] = round(max(0.0, min(score, 100.0)), 1)
        sorted_cards = sorted(
            cards,
            key=lambda c: c.get("preliminary_match_score", 50),
            reverse=True,
        )
        logger.info(
            f"[JobCapture] 轻量打分完成: top3 = {[(c.get('job_title'), c.get('preliminary_match_score')) for c in sorted_cards[:3]]}"
        )
        return sorted_cards
    except Exception as e:
        logger.warning("[JobCapture] 轻量匹配度模型打分失败，回退关键词排序: %s", type(e).__name__)
        for idx, card in enumerate(cards):
            card["preliminary_match_score"] = deterministic_scores.get(idx, 35.0)
        return sorted(cards, key=lambda item: item.get("preliminary_match_score", 35.0), reverse=True)


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
    cards = _sanitize_cards(raw_cards)

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
        scored_cards = await _score_job_cards_by_match(
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


async def import_cards_to_library(
    user_id: str,
    cards: list[dict[str, Any]],
    city: Optional[str] = None,
) -> Dict[str, Any]:
    """确定性保存用户确认的待入库卡片，不触发任何模型或后台任务。

    岗位按来源哈希去重；重复卡片复用已有岗位记录。历史资产字段只在读取
    既有记录时保留，本入口不会创建或更新 AgentRun、Resume Generation、
    Greeting、JD 分析或资产跟踪状态。
    """
    valid_cards = _sanitize_cards(cards)
    if not valid_cards:
        return {
            "success": False,
            "total": 0,
            "jobs": [],
            "duplicates": 0,
            "failed": [],
            "message": "入库内容中没有有效岗位卡片",
        }

    results: list = []
    failures: list = []
    duplicates = 0

    for idx, card in enumerate(valid_cards, 1):
        company = card.get("company_name", "")
        title = card.get("job_title", "")
        salary = card.get("salary_text", "")
        city_val = card.get("city", "") or (city or "")
        jd_text = card.get("job_description") or card.get("title_summary") or title
        source_url = str(card.get("source_url") or "")
        match_score = card.get("preliminary_match_score")

        logger.info(
            "[JobCapture] 确定性入库 [%s/%s]: %s - %s",
            idx,
            len(valid_cards),
            company,
            title,
        )
        try:
            cap = await _normalize_and_save(
                {
                    **card,
                    "city": city_val,
                    "preliminary_match_score": match_score,
                },
                user_id,
                "boss",
                source_url=source_url,
                source_text=jd_text,
            )
        except Exception as exc:
            logger.warning("[JobCapture] 卡片 %s 入库失败: %s", idx, type(exc).__name__)
            failures.append({
                "company_name": company,
                "job_title": title,
                "reason": str(exc),
                "source_url": source_url,
            })
            continue

        if not cap.get("success"):
            failures.append({
                "company_name": company,
                "job_title": title,
                "reason": cap.get("message", ""),
                "source_url": source_url,
            })
            continue

        raw_job_id = cap.get("job_id")
        if not isinstance(raw_job_id, (int, str)):
            failures.append({
                "company_name": company,
                "job_title": title,
                "reason": "岗位保存返回了无效 ID",
                "source_url": source_url,
            })
            continue

        job_id = int(raw_job_id)
        if cap.get("is_duplicate"):
            duplicates += 1

        results.append({
            "job_id": job_id,
            "source_url": source_url,
            "company_name": company,
            "company_size_text": card.get("company_size_text", ""),
            "job_title": title,
            "job_description": jd_text,
            "salary_text": salary,
            "city": city_val,
            "match_score": match_score,
            "custom_resume_id": None,
            "greetings": [],
            "risk_flags": [],
            "asset_run_id": None,
            "asset_status": None,
        })

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
