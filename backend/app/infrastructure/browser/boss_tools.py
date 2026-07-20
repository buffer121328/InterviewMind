"""
BOSS 直聘 ReAct Agent 工具集
"""

import logging
from typing import Optional, Dict, Any, List
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)


async def open_boss_search_page(query: str, city: str = "", wait_seconds: int = 8,
                                wait_for_captcha: bool = True, captcha_timeout: int = 180) -> str:
    """通过统一的持久化 Playwright 会话读取 BOSS 搜索页。"""
    search_url = f"https://www.zhipin.com/web/geek/job?query={quote_plus(query)}"
    if city:
        search_url += f"&city={quote_plus(city)}"
    logger.info(f"[BossTool] 打开 BOSS 搜索页: query={query!r}")

    from .job_capture_service import _fetch_page_text_browser

    manual_wait_seconds = captcha_timeout if wait_for_captcha else max(wait_seconds, 1)
    text = await _fetch_page_text_browser(
        search_url,
        headless=False,
        manual_wait_seconds=manual_wait_seconds,
    )
    if not text:
        return "ERROR: 无法读取 BOSS 页面，请在项目专用浏览器中完成登录后重试"
    if "请稍候" in text or "安全验证" in text or len(text) < 200:
        return "CAPTCHA: 需要反爬验证，请在项目专用浏览器中手动完成后重试"
    logger.info(f"[BossTool] 抓取成功: {len(text)} 字符")
    return text


async def extract_job_cards_from_page(page_text: str, top_n: int = 10,
                                      query_filter: str = "",
                                      api_config: Optional[dict] = None) -> List[Dict[str, Any]]:
    """用 LLM 从搜索结果页文本中提取岗位卡片"""
    from app.infrastructure.llm.llm_utils import invoke_structured
    from app.schemas.llm_outputs import JobCardList
    from app.prompts.jobs import build_job_card_extraction_prompt

    for marker in ["综合排序", "最新优先", "BOSS直聘"]:
        if marker in page_text:
            pos = page_text.find(marker)
            if pos > 0:
                page_text = page_text[pos:]
                break
    snippet = page_text[:6000]
    prompt = build_job_card_extraction_prompt(page_text=snippet, top_n=top_n, keyword=query_filter)
    try:
        result = await invoke_structured(prompt=prompt, output_model=JobCardList,
                                         api_config=api_config, channel="fast")
        cards = [c.model_dump() for c in result.cards[:top_n]]
        logger.info(f"[BossTool] LLM 提取到 {len(cards)} 个岗位卡片")
        return cards
    except Exception as e:
        logger.error(f"[BossTool] 提取失败: {e}")
        return []


async def score_jobs_by_match(cards: List[Dict[str, Any]], resume_content: str,
                              query: str = "", api_config: Optional[dict] = None) -> List[Dict[str, Any]]:
    """LLM 对岗位卡片做匹配度打分排序"""
    from app.infrastructure.llm import llms
    import json as _json
    from app.prompts.jobs import build_job_card_scoring_prompt
    if not cards or not resume_content:
        return cards
    cards_brief = [{"id": i, "title": c.get("job_title", "")[:50],
                    "company": c.get("company_name", "")[:30],
                    "salary": c.get("salary_text", ""), "city": c.get("city", ""),
                    "jd_short": (c.get("job_description") or "")[:120]} for i, c in enumerate(cards[:15])]
    prompt = build_job_card_scoring_prompt(cards_brief=cards_brief, resume_context=resume_content[:800])
    try:
        response = await llms.invoke_text(prompt, api_config, channel="fast")
        text_strip = response.content.strip() if hasattr(response, "content") else str(response).strip()
        if text_strip.startswith("```"):
            text_strip = text_strip.split("```")[1]
            if text_strip.startswith("json"):
                text_strip = text_strip[4:]
        parsed = _json.loads(text_strip)
        score_map = {s.get("id"): s.get("score", 50) for s in parsed.get("scores", []) if isinstance(s, dict)}
        for i, c in enumerate(cards):
            c["preliminary_match_score"] = score_map.get(i, 50)
        return sorted(cards, key=lambda c: c.get("preliminary_match_score", 50), reverse=True)
    except Exception as e:
        logger.warning(f"[BossTool] 打分失败: {e}")
        return cards


async def save_job_to_database(raw_data: Dict[str, Any], user_id: str,
                               platform: str = "boss", source_url: str = "") -> Dict[str, Any]:
    """标准化并保存岗位到数据库"""
    from .job_normalizer import normalize_company_name, normalize_salary, extract_keywords, compute_source_hash
    from .job_deduper import is_duplicate
    from app.infrastructure.db.repositories.jobs.job_capture_repo import get_job_capture_repo
    from datetime import datetime
    company = normalize_company_name(raw_data.get("company_name", ""))
    title = raw_data.get("job_title", "").strip()
    jd = raw_data.get("job_description", "")
    salary = normalize_salary(raw_data.get("salary_text", ""))
    city = raw_data.get("city", "").strip()
    keywords = extract_keywords(jd)
    source_hash = compute_source_hash(company_name=company, job_title=title,
                                      source_url=source_url, platform=platform)
    if await is_duplicate(source_hash, user_id):
        return {"success": True, "job_id": None, "is_duplicate": True, "message": f"岗位已存在: {company} - {title}"}
    try:
        repo = get_job_capture_repo()
        job_id = await repo.save_job(user_id=user_id, job_data={
            "platform": platform, "source_url": source_url, "company_name": company,
            "job_title": title, "job_description": jd, "salary_text": salary["text"],
            "salary_min": salary["min"], "salary_max": salary["max"], "city": city,
            "tags": keywords, "source_hash": source_hash, "status": "pending",
            "captured_at": datetime.now().isoformat()})
        return {"success": True, "job_id": job_id, "is_duplicate": False,
                "normalized_job": {"company_name": company, "job_title": title, "city": city},
                "message": f"保存成功: {company} - {title}"}
    except Exception as e:
        return {"success": False, "job_id": None, "message": f"保存失败: {e}"}


async def generate_job_assets(job_id: int, user_id: str, resume_content: str,
                              api_config: Optional[dict] = None) -> Dict[str, Any]:
    """为指定岗位生成投递资产"""
    from app.infrastructure.browser.job_asset_orchestrator import generate_assets as _gen
    try:
        result = await _gen(job_id=job_id, user_id=user_id, resume_content=resume_content,
                            api_config=api_config)
        if result.get("success") and result.get("assets"):
            assets = result["assets"]
            match_score = assets.jd_analysis.get("overall_match_score") if assets.jd_analysis else None
            greetings = [{"tone": g.tone, "message_text": g.message_text[:100]} for g in (assets.greetings or [])]
            return {"success": True, "match_score": match_score, "greetings_count": len(greetings),
                    "greetings": greetings, "message": f"资产生成成功 (匹配度: {match_score}%)"}
        return {"success": False, "message": result.get("message", "资产生成失败")}
    except Exception as e:
        return {"success": False, "message": f"资产生成失败: {e}"}


async def check_environment() -> str:
    """检测当前环境是否支持 BOSS 自动化"""
    try:
        from .boss_automation_client import get_boss_automation_client

        health = await get_boss_automation_client().health()
        if not health.get("playwright_available"):
            return "环境问题:\n❌ 宿主机 Playwright 未安装"
    except Exception as exc:
        logger.warning("[BossTool] 宿主机服务检查失败: %s", exc)
        return "环境问题:\n⚠️ 无法连接 BOSS 宿主机服务"
    return "✅ 环境正常（宿主机 Playwright 持久化会话）"
