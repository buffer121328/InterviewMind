"""
岗位采集服务

支持两种采集方式：
1. URL 采集：HTTP 抓取页面 → LLM 提取结构化字段
2. 手动粘贴：用户粘贴 JD 原文 → LLM 提取结构化字段

采集后自动标准化 + 去重检测 + 按匹配度排序。
"""

import asyncio
import platform as _platform

import logging
from typing import Dict, Any, Optional
from datetime import datetime

from .job_normalizer import (
    normalize_company_name,
    normalize_salary,
    extract_keywords,
    compute_source_hash,
)
from .job_deduper import is_duplicate

logger = logging.getLogger(__name__)


async def capture_from_url(
    url: str,
    user_id: str,
    platform: str = "boss",
    company_name_hint: str = "",
    job_title_hint: str = "",
    api_config: Optional[dict] = None,
    cookies: Optional[list] = None,
    headless: bool = True,
) -> Dict[str, Any]:
    """
    从 URL 采集岗位信息。

    Args:
        url: 岗位页面 URL
        user_id: 用户 ID
        platform: 平台标识
        company_name_hint: 公司名提示
        job_title_hint: 岗位名提示
        api_config: API 配置
        cookies: 用户登录 Cookies（List[Playwright Cookie Dict]）
        headless: 浏览器无头模式（无 cookies 时建议 False 让用户完成验证）

    Returns:
        {"success": bool, "job_id": int, "normalized_job": dict, "is_duplicate": bool}
    """
    from app.services.llm_utils import invoke_structured
    from pydantic import BaseModel

    class JobExtractionOutput(BaseModel):
        company_name: str
        job_title: str
        job_description: str
        salary_text: str
        city: str

    # Step 1: 抓取页面文本（优先 HTTP，失败时用浏览器渲染）
    page_text = await _fetch_page_text(url)
    browser_used = False

    # BOSS直聘等平台有反爬安全页，HTTP 拿到的内容不含岗位信息
    # 判断标准：提取后字段全空 → 切换到浏览器渲染
    _needs_browser = False
    if page_text:
        # 快速检测：安全页面通常很短且包含特定关键词
        if len(page_text) < 500 or "请稍候" in page_text or "安全验证" in page_text:
            _needs_browser = True
            logger.info("[JobCapture] HTTP 获取到安全验证页，切换到浏览器模式")

    if not page_text or _needs_browser:
        logger.info("[JobCapture] 尝试浏览器渲染...")
        browser_text = await _fetch_page_text_browser(url, cookies=cookies, headless=headless)
        if browser_text:
            page_text = browser_text
            browser_used = True
        elif not page_text:
            return {
                "success": False,
                "message": "无法获取页面内容，请检查链接或尝试手动粘贴 JD",
                "is_duplicate": False,
            }

    # Step 2: LLM 提取结构化字段
    try:
        extraction = await invoke_structured(
            prompt=_build_extraction_prompt(
                page_text, company_name_hint, job_title_hint
            ),
            output_model=JobExtractionOutput,
            api_config=api_config,
            channel="smart",
        )
        raw_data = extraction.model_dump()
    except Exception as e:
        logger.error(f"[JobCapture] URL 提取失败: {e}")
        return {
            "success": False,
            "message": f"岗位信息提取失败: {e}",
            "is_duplicate": False,
        }

    # Step 2.5: LLM 提取后仍为空 → 浏览器重试
    if not raw_data.get("company_name") and not raw_data.get("job_title") and not browser_used:
        logger.info("[JobCapture] LLM 提取为空，切换到浏览器模式重试...")
        browser_text = await _fetch_page_text_browser(url, cookies=cookies, headless=headless)
        if browser_text:
            try:
                extraction2 = await invoke_structured(
                    prompt=_build_extraction_prompt(
                        browser_text, company_name_hint, job_title_hint
                    ),
                    output_model=JobExtractionOutput,
                    api_config=api_config,
                    channel="smart",
                )
                raw_data = extraction2.model_dump()
            except Exception as e:
                logger.warning(f"[JobCapture] 浏览器模式 LLM 提取也失败: {e}")

    # Step 3: 标准化 + 去重 + 保存
    return await _normalize_and_save(
        raw_data, user_id, platform, url, page_text
    )


async def capture_from_text(
    jd_text: str,
    user_id: str,
    platform: str = "manual",
    company_name_hint: str = "",
    job_title_hint: str = "",
    api_config: Optional[dict] = None,
) -> Dict[str, Any]:
    """
    从用户手动粘贴的 JD 文本采集岗位信息。
    
    Args:
        jd_text: JD 文本
        user_id: 用户 ID
        platform: 平台标识
        company_name_hint: 公司名提示
        job_title_hint: 岗位名提示
        api_config: API 配置
        
    Returns:
        {"success": bool, "job_id": int, "normalized_job": dict, "is_duplicate": bool}
    """
    from app.services.llm_utils import invoke_structured
    from pydantic import BaseModel

    class JobExtractionOutput(BaseModel):
        company_name: str
        job_title: str
        job_description: str
        salary_text: str
        city: str

    # LLM 提取结构化字段
    try:
        extraction = await invoke_structured(
            prompt=_build_extraction_prompt(
                jd_text[:3000], company_name_hint, job_title_hint
            ),
            output_model=JobExtractionOutput,
            api_config=api_config,
            channel="smart",
        )
        raw_data = extraction.model_dump()
    except Exception as e:
        logger.error(f"[JobCapture] 文本提取失败: {e}")
        return {
            "success": False,
            "message": f"岗位信息提取失败: {e}",
            "is_duplicate": False,
        }

    # 标准化 + 去重 + 保存
    return await _normalize_and_save(
        raw_data, user_id, platform, source_url="", source_text=jd_text
    )


# ============================================================================
# 内部函数
# ============================================================================

async def _normalize_and_save(
    raw_data: dict,
    user_id: str,
    platform: str,
    source_url: str = "",
    source_text: str = "",
) -> Dict[str, Any]:
    """标准化、去重并保存岗位记录"""
    from app.repositories.jobs.job_capture_repo import get_job_capture_repo

    company_name = normalize_company_name(
        raw_data.get("company_name", "")
    )
    job_title = raw_data.get("job_title", "").strip()
    job_description = raw_data.get("job_description", source_text)
    salary_info = normalize_salary(raw_data.get("salary_text", ""))
    city = raw_data.get("city", "").strip()
    keywords = extract_keywords(job_description)

    # 计算去重哈希
    source_hash = compute_source_hash(
        company_name=company_name,
        job_title=job_title,
        source_url=source_url,
        platform=platform,
    )

    # 去重检测
    duplicated = await is_duplicate(source_hash, user_id)
    if duplicated:
        return {
            "success": True,
            "message": "该岗位已采集过",
            "is_duplicate": True,
        }

    # 保存到数据库
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
    except Exception as e:
        logger.error(f"[JobCapture] 保存岗位失败: {e}")
        return {
            "success": False,
            "message": f"保存岗位失败: {e}",
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


async def _fetch_via_existing_chrome(url: str) -> str:
    """
    通过 AppleScript 连接用户已打开的 Chrome 浏览器，读取已存在 tab 的页面文本。
    仅 macOS 可用。绕过反爬最有效——使用用户真实浏览器、真实登录态。

    Args:
        url: 目标岗位 URL（用于在所有 tab 中匹配）
    """
    if _platform.system() != "Darwin":
        return ""

    # 提取 URL 关键段用于匹配（例如 zhipin.com/job_detail/afa3101d...）
    import re
    match = re.search(r"(zhipin\.com/job_detail/[a-zA-Z0-9]+)", url)
    if not match:
        return ""
    url_key = match.group(1)

    script = f"""
    on findAndRead()
        tell application "Google Chrome"
            repeat with w in windows
                repeat with t in tabs of w
                    set tabURL to URL of t
                    if tabURL contains "{url_key}" then
                        try
                            tell t to execute javascript "document.body.innerText"
                            return result
                        on error
                            return ""
                        end try
                    end if
                end repeat
            end repeat
        end tell
        return ""
    end findAndRead
    findAndRead()
    """

    try:
        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
        text = stdout.decode("utf-8", errors="ignore").strip()
        if text and len(text) > 200 and "请稍候" not in text:
            return text
        return ""
    except Exception as e:
        logger.debug(f"[JobCapture] AppleScript Chrome 读取失败: {e}")
        return ""


async def _fetch_page_text_browser(
    url: str,
    cookies: Optional[list] = None,
    headless: bool = True,
) -> str:
    """
    通过浏览器抓取页面文本。优先级：
    1. 连接用户已打开的 Chrome（macOS AppleScript），绕过反爬
    2. 启动 Playwright 浏览器（支持 cookies / 有头等模式）

    Args:
        url: 岗位页面 URL
        cookies: 用户登录 Cookies（List[Playwright Cookie Dict]）
        headless: 是否无头模式。无 cookies 时建议 False，让用户在弹出窗口中
                  完成验证码/登录，完成后浏览器自动读取页面内容。
    """
    # 优先尝试连接用户已打开的 Chrome（绕过反爬最有效）
    text = await _fetch_via_existing_chrome(url)
    if text:
        logger.info(f"[JobCapture] 通过已打开的 Chrome 抓取成功, {len(text)} 字符")
        return text

    # 降级到 Playwright
    try:
        from app.services.jobs.browser_runner import start_browser, open_job_page, scrape_page_text

        pw, browser, context = await start_browser(headless=headless)
        try:
            # 注入用户 cookies（如果提供）
            if cookies:
                await context.add_cookies(cookies)
                logger.info(f"[JobCapture] 已注入 {len(cookies)} 条 cookies")

            page = await open_job_page(context, url)

            # 无 cookies 且非 headless 时，等用户完成验证（最多 90 秒）
            if not cookies and not headless:
                logger.info("[JobCapture] 等待用户在浏览器中完成验证（最多 90 秒）...")
                try:
                    # 等待岗位页面加载（URL 跳回 job_detail 或页面包含 "岗位" 字样）
                    await page.wait_for_function(
                        """() => {
                            const t = document.body.innerText;
                            return (t.includes('岗位') || t.includes('职位')) && !t.includes('请稍候');
                        }""",
                        timeout=90000,
                    )
                except Exception:
                    logger.warning("[JobCapture] 等待用户验证超时")

            text = await scrape_page_text(page)
            await page.close()
            if text:
                logger.info(f"[JobCapture] 浏览器抓取成功, {len(text)} 字符")
            return text
        finally:
            await context.close()
            await browser.close()
            await pw.stop()
    except ImportError:
        logger.warning("[JobCapture] Playwright 未安装，无法使用浏览器模式")
        return ""
    except Exception as e:
        logger.warning(f"[JobCapture] 浏览器抓取失败: {e}")
        return ""


async def _fetch_page_text(url: str) -> str:
    """通过 HTTP 抓取页面文本（降级方案，优先用浏览器）"""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                },
            )
            resp.raise_for_status()
            html = resp.text

            # 简单提取可见文本
            import re
            # 去除 script/style 标签
            text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
            text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
            # 去除 HTML 标签
            text = re.sub(r"<[^>]+>", " ", text)
            # 去除多余空白
            text = re.sub(r"\s+", " ", text).strip()

            return text[:5000]  # 取前 5000 字符
    except Exception as e:
        logger.warning(f"[JobCapture] HTTP 抓取失败: {e}")
        return ""


def _build_extraction_prompt(
    page_text: str,
    company_name_hint: str = "",
    job_title_hint: str = "",
) -> str:
    """构建 LLM 提取 prompt"""
    hint_section = ""
    if company_name_hint or job_title_hint:
        hint_section = f"""
【用户提示】：
- 可能的公司名: {company_name_hint or '无'}
- 可能的岗位名: {job_title_hint or '无'}
"""

    return f"""你是一位「招聘信息提取专家」。请从以下页面文本中提取岗位关键信息。

【页面文本】：
{page_text[:3000]}

{hint_section}

请提取并输出 JSON：
{{
    "company_name": "标准化公司名",
    "job_title": "岗位名称",
    "job_description": "完整的 JD 正文",
    "salary_text": "薪资范围原文",
    "city": "工作城市"
}}

要求：
1. company_name 只输出核心公司名，去掉"有限公司"等后缀
2. job_title 只输出岗位名，不要包含经验年限或薪资
3. job_description 保留 JD 的核心内容（职责+要求）
4. 如果某个字段无法从文本中提取，输出空字符串"""


# ============================================================================
# BOSS 推荐页批量抓取（半自动化）
# ============================================================================

async def _open_and_read_in_chrome(
    url: str,
    wait_seconds: int = 8,
    wait_for_user_captcha: bool = False,
    captcha_timeout: int = 120,
) -> str:
    """
    通过 AppleScript 让用户已打开的 Chrome 在当前窗口新开 tab 访问 url，
    等待若干秒后读取 body innerText（不关闭 tab）。

    Args:
        url: 目标 URL
        wait_seconds: 初次等待页面加载秒数
        wait_for_user_captcha: True 时检测到反爬页后阻塞等待用户手动完成验证，
                               最长 captcha_timeout 秒；每隔 5 秒重读一次页面。
        captcha_timeout: 等待用户完成验证码的最长秒数

    仅 macOS 可用。若 Chrome 未开启 AppleScript JS 权限则返回空字符串。
    """
    if _platform.system() != "Darwin":
        return ""

    def _build_script(target_url: str, sec: int) -> str:
        return f'''
        on run
            tell application "Google Chrome"
                if (count of windows) = 0 then
                    make new window
                end if
                tell window 1
                    set newTab to make new tab with properties {{URL:"{target_url}"}}
                end tell
                delay {sec}
                try
                    tell newTab to execute javascript "document.body.innerText"
                    set pageText to result
                    return pageText
                on error errMsg
                    return ""
                end try
            end tell
        end run
        '''

    def _build_recheck_script() -> str:
        # 读取最后一个 tab（刚开的那个）的当前内容
        return '''
        on run
            tell application "Google Chrome"
                if (count of windows) = 0 then return ""
                tell window 1
                    set t to active tab
                    try
                        tell t to execute javascript "document.body.innerText"
                        return result
                    on error
                        return ""
                    end try
                end tell
            end tell
        end run
        '''

    async def _run_applescript(script: str, timeout: int) -> str:
        try:
            proc = await asyncio.create_subprocess_exec(
                "osascript", "-e", script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return stdout.decode("utf-8", errors="ignore").strip()
        except Exception as e:
            logger.warning(f"[JobCapture] AppleScript 调用失败: {e}")
            return ""

    # Step 1: 新开 tab 访问 url，初次等待
    text = await _run_applescript(_build_script(url, wait_seconds), wait_seconds + 20)

    # Step 2: 若未启用反爬等待模式，直接返回
    if not wait_for_user_captcha:
        return text

    # Step 3: 检测反爬页，若被拦截则循环等待
    is_captcha = bool(text) and ("请稍候" in text or "安全验证" in text or "verify.html" in text or len(text) < 200)
    if not is_captcha:
        return text

    logger.info(f"[JobCapture] 检测到反爬验证页，等待用户在 Chrome 中手动完成验证（最多 {captcha_timeout}秒）...")

    waited = 0
    recheck_script = _build_recheck_script()
    while waited < captcha_timeout:
        await asyncio.sleep(5)
        waited += 5
        text = await _run_applescript(recheck_script, 15)
        if not text:
            continue
        # 仍是验证页 → 继续等
        if "请稍候" in text or "安全验证" in text or "verify.html" in text:
            continue
        if len(text) < 200:
            continue
        # 验证完成，回到目标页（或被重定向回业务页）
        logger.info(f"[JobCapture] 用户已完成验证（耗时 {waited} 秒），抓到 {len(text)} 字符")
        return text

    logger.warning(f"[JobCapture] 用户验证超时（{captcha_timeout}秒），放弃抓取")
    return ""


async def _llm_extract_job_cards(
    page_text: str,
    top_n: int = 5,
    query_filter: str = "",
) -> list:
    """
    用 LLM 从 BOSS 推荐页文本中提取前 N 个岗位卡片。

    Args:
        page_text: 推荐页 body innerText
        top_n: 提取前 N 个岗位
        query_filter: 用户搜索关键词（用于过滤/排序，可空)

    Returns:
        List[dict]，每项包含 company_name / job_title / salary_text / city /
        title_summary / job_description
    """
    from app.services.llm_utils import invoke_structured
    from app.schemas.llm_outputs import JobCardList

    # 截断页面文本，从岗位列表区域开始（搜索页通常有「综合排序」「最新」分隔栏）
    # 找到第一个明显的岗位列表起始位置
    for marker in ["综合排序", "最新优先", "BOSS直聘", "面试", "招聘"]:
        if marker in page_text:
            pos = page_text.find(marker)
            if pos > 0:
                page_text = page_text[pos:]
                break
    snippet = page_text[:6000]

    filter_hint = ""
    if query_filter:
        filter_hint = (
            f"\n【搜索关键词】用户搜索的是「{query_filter}」相关岗位。\n"
            f"请优先返回与该方向最相关的前 {top_n} 个岗位；\n"
            f"如果搜索结果中没有理想匹配，就返回最靠前的 {top_n} 个，不要硬凑。"
        )

    prompt = f"""你是一位招聘数据提取专家。以下文本来自 BOSS直聘搜索结果页。
请提取前 {top_n} 个岗位卡片的结构化信息。

【页面文本】：
{snippet}
{filter_hint}

注意：
1. 推荐页卡片信息有限，job_description 可能只有岗位一句话简介 + 经验/学历要求，写出来即可
2. company_name 去掉"有限公司"等后缀
3. salary_text 保留原文（如 "15-30K" 或 "50-55元/时"）
4. city 提取可见的城市/区域（如 "广州·天河区"，输出 "广州" 即可）
5. title_summary 填卡片上额外可见的经验/学历要求（如 "本科 3-5年"），没有就空

Respond in JSON format."""

    try:
        result = await invoke_structured(
            prompt=prompt,
            output_model=JobCardList,
            api_config=None,  # 由调用方传入
            channel="fast",
        )
        return [c.model_dump() for c in result.cards[:top_n]]
    except Exception as e:
        logger.error(f"[JobCapture] 推荐页岗位提取失败: {e}")
        return []


async def _score_job_cards_by_match(
    cards: list,
    resume_content: str,
    query: str,
    api_config: Optional[dict] = None,
) -> list:
    """
    用 fast 通道一次性对所有候选岗位做轻量匹配度打分，按分数降序排序。

    这一步不调用 jd_matcher（那个调用太重，会生成详细分析+建议），
    仅让 LLM 一次性对每张卡片输出一个 0-100 的匹配分数。

    Args:
        cards: 由 _llm_extract_job_cards 返回的卡片列表
        resume_content: 简历内容
        query: 用户搜索的关键词
        api_config: API 配置

    Returns:
        按匹配度降序的卡片列表，每张卡片新增一个 preliminary_match_score 字段
    """
    from app.services import llms
    import json as _json

    if not cards or not resume_content:
        return cards

    # 构造紧凑的卡片列表（截断 prompt 大小）
    cards_brief = []
    for idx, c in enumerate(cards[:15]):
        cards_brief.append({
            "id": idx,
            "title": c.get("job_title", "")[:50],
            "company": c.get("company_name", "")[:30],
            "salary": c.get("salary_text", ""),
            "city": c.get("city", ""),
            "jd_short": (c.get("job_description") or c.get("title_summary") or "")[:120],
        })

    prompt = f"""你是岗位匹配评估专家。下面是 {len(cards_brief)} 个岗位的简短信息，以及候选人简历摘要。
请基于简历与「查询岗位方向」，对每张卡片输出一个 0-100 的匹配分数。
越高表示越匹配。评分维度包括技能匹配、经验级别匹配、领域相关性、薪资相称性。

【查询岗位关键词】{query}

【候选人简历摘要】
{resume_content[:800]}

【候选岗位列表】
{_json.dumps(cards_brief, ensure_ascii=False)}

【输出 JSON 格式】必须是一个 JSON 对象：
{{
  "scores": [
    {{"id": 0, "score": 75, "reason": "匹配度评价一句话"}},
    {{"id": 1, "score": 80, "reason": "..."}}
  ]
}}

只输出 JSON 对象，不要其它解释。

Respond in JSON format."""

    try:
        fast_llm = llms.get_llm_for_request(api_config, channel="fast")
        response = await fast_llm.ainvoke(prompt)
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

        # 按分数给每张卡片打标并排序
        for idx, c in enumerate(cards):
            c["preliminary_match_score"] = score_map.get(idx, 50)
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
        logger.warning(f"[JobCapture] 轻量匹配度打分失败，跳过排序: {e}")
        return cards


async def capture_from_recommendations(
    user_id: str,
    query: str,
    resume_content: str,
    api_config: Optional[dict] = None,
    top_n: int = 5,
    city: Optional[str] = None,
) -> Dict[str, Any]:
    """
    批量抓取 BOSS 推荐页前 N 个岗位 + 生成投递资产。

    Args:
        user_id: 用户 ID
        query: 搜索关键词（可空）
        resume_content: 候选人基础简历
        api_config: API 配置（必需，内含 smart/fast 通道）
        top_n: 抓取前 N 个岗位，默认 5，上限 10
        city: 城市提示（可选，目前 BOSS 按 IP 自动定位）

    Returns:
        {"success": bool, "jobs": List[dict], "total": int, "message": str}
    """
    from app.services.jobs.job_asset_orchestrator import generate_assets

    if not api_config:
        return {
            "success": False, "total": 0, "jobs": [],
            "message": "未检测到 API 配置。请在请求中传入 api_config。",
        }

    # Step 1: 构造 BOSS 搜索页 URL 并通过 AppleScript 在 Chrome 新开 tab
    # 搜索页 URL: https://www.zhipin.com/web/geek/job?query=xxx&city=100010000
    # city 不传时 BOSS 会按 IP 自动定位
    from urllib.parse import quote_plus
    search_url = f"https://www.zhipin.com/web/geek/job?query={quote_plus(query)}"
    if city:
        # 常见城市码：北京 101010100 / 上海 101020100 / 广州 101280100 / 深圳 101280600
        # 杭州 101210100 / 成都 101270100 / 全国 100010000
        # 这里仅作 URL 注入，BOSS 会按 IP 自动定位，city 参数仅作标记
        search_url += f"&city={quote_plus(city)}"

    logger.info(f"[JobCapture] 批量采集启动: user={user_id}, query={query!r}, top_n={top_n}, url={search_url}")
    page_text = await _open_and_read_in_chrome(
        search_url,
        wait_seconds=8,
        wait_for_user_captcha=True,   # 检测到反爬页 → 等用户手动完成验证
        captcha_timeout=180,           # 最长等 3 分钟
    )

    if not page_text:
        return {
            "success": False, "total": 0, "jobs": [],
            "message": "无法读取 Chrome 页面。请确认：1) Chrome 已打开并登录 BOSS；2) 菜单 查看→开发者→允许 Apple 事件中的 JavaScript 已启用；3) 若弹出安全验证页，请在 Chrome 中手动完成验证（最长等待 3 分钟）。",
        }

    # 反爬兜底检测（即使开了 wait_for_user_captcha 也再确认一次）
    if "请稍候" in page_text or "安全验证" in page_text or "verify.html" in page_text:
        return {
            "success": False, "total": 0, "jobs": [],
            "message": "BOSS 仍处于反爬安全验证页。请确认在 Chrome 中已手动完成滑动验证，然后重新调用本接口。",
        }

    # 搜索页内容检测：BOSS 搜索页通常包含「BOSS直聘」「招聘」「综合」「最新」等关键词
    if "招聘" not in page_text and "BOSS" not in page_text.upper():
        return {
            "success": False, "total": 0, "jobs": [],
            "message": "未能识别 BOSS 搜索页内容（页面里没找到「招聘」相关元素）。",
        }

    # Step 2: LLM 提取卡片
    # 临时 monkey-patch api_config 给 _llm_extract_job_cards 内的 invoke_structured
    # （它原本写死 api_config=None，我们要传入）
    _orig_extract = _llm_extract_job_cards

    async def _extract_with_api_config(page_text_arg, top_n_arg, query_filter_arg):
        from app.services.llm_utils import invoke_structured
        from app.schemas.llm_outputs import JobCardList

        # 搜索页找起始 marker
        for marker in ["综合排序", "最新优先", "BOSS直聘", "面试", "招聘"]:
            if marker in page_text_arg:
                pos = page_text_arg.find(marker)
                if pos > 0:
                    page_text_arg = page_text_arg[pos:]
                    break

        snippet = page_text_arg[:6000]
        filter_hint = ""
        if query_filter_arg:
            filter_hint = (
                f"\n【搜索关键词】用户搜索的是「{query_filter_arg}」相关岗位。\n"
                f"请优先返回与该方向最相关的前 {top_n_arg} 个岗位；"
                f"如果搜索结果中没有理想匹配，就返回最靠前的 {top_n_arg} 个，不要硬凑。"
            )

        prompt = f"""你是一位招聘数据提取专家。以下文本来自 BOSS直聘搜索结果页。
请提取前 {top_n_arg} 个岗位卡片的结构化信息。

【页面文本】：
{snippet}
{filter_hint}

要求：
1. 推荐页卡片信息有限，job_description 可能只有岗位一句话简介 + 经验/学历要求，写出来即可
2. company_name 去掉"有限公司"等后缀
3. salary_text 保留原文（如 "15-30K" 或 "50-55元/时"）
4. city 提取可见的城市/区域（如 "广州·天河区"，输出 "广州" 即可）
5. title_summary 填卡片上额外可见的经验/学历要求（如 "本科 3-5年"），没有就空

【输出格式】必须是一个 JSON 对象，包含 cards 数组字段，形如：
{{
  "cards": [
    {{"company_name": "示例公司", "job_title": "Java工程师", "salary_text": "15-30K", "city": "广州", "title_summary": "本科 3-5年", "job_description": "...")
    }}
  ]
}}

请严格按上述 JSON 对象结构输出，顶层必须是 {{"cards": [...]}}，不要直接输出顶层数组。

Respond in JSON format."""

        try:
            result = await invoke_structured(
                prompt=prompt, output_model=JobCardList,
                api_config=api_config, channel="fast",
            )
            return [c.model_dump() for c in result.cards[:top_n_arg]]
        except Exception as e:
            logger.error(f"[JobCapture] 推荐页岗位提取失败: {e}")
            return []

    # 多提取一些卡片用于后续匹配度排序
    fetch_count = min(top_n * 4, 15)
    cards = await _extract_with_api_config(page_text, fetch_count, query)

    if not cards:
        return {
            "success": False, "total": 0, "jobs": [],
            "message": "未能从搜索结果页提取到任何岗位卡片，请检查 Chrome 中 BOSS 页面是否已加载。",
        }

    logger.info(f"[JobCapture] LLM 提取到 {len(cards)} 个候选岗位卡片")

    # Step 2.5: 用 fast 通道做轻量匹配度打分，按分取前 top_n 个
    if query and resume_content and len(cards) > top_n:
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

    # Step 3: 对每张卡片复用 capture_from_text + generate_assets
    results: list = []
    failures: list = []

    for idx, card in enumerate(cards, 1):
        company = card.get("company_name", "")
        title = card.get("job_title", "")
        salary = card.get("salary_text", "")
        city_val = card.get("city", "") or (city or "")
        jd_text = card.get("job_description") or card.get("title_summary") or title

        logger.info(f"[JobCapture] [{idx}/{len(cards)}] 处理: {company} - {title}")

        # 复用 capture_from_text：标准化 + 入库
        try:
            cap = await capture_from_text(
                jd_text=jd_text,
                user_id=user_id,
                platform="boss",
                company_name_hint=company,
                job_title_hint=title,
                api_config=api_config,
            )
        except Exception as e:
            logger.warning(f"[JobCapture] 卡片 {idx} 标准化失败: {e}")
            failures.append({"company": company, "title": title, "reason": str(e)})
            continue

        if not cap.get("success"):
            failures.append({"company": company, "title": title, "reason": cap.get("message", "")})
            continue

        job_id = cap.get("job_id")

        # 复用 generate_assets：JD分析 + 定制简历 + 打招呼文案
        asset_result = None
        risk_flags: list = []
        match_score = None
        custom_resume_id = None
        greetings: list = []

        try:
            asset_result = await generate_assets(
                job_id=job_id,
                user_id=user_id,
                resume_content=resume_content,
                api_config=api_config,
            )
            if asset_result.get("success") and asset_result.get("assets"):
                assets_obj = asset_result["assets"]
                risk_flags = list(assets_obj.risk_flags or [])
                if assets_obj.jd_analysis:
                    match_score = assets_obj.jd_analysis.get("overall_match_score")
                custom_resume_id = assets_obj.custom_resume_id
                for g in (assets_obj.greetings or []):
                    greetings.append({
                        "tone": g.tone,
                        "message_text": g.message_text,
                        "highlights_used": g.highlights_used,
                        "risk_notes": g.risk_notes,
                    })
        except Exception as e:
            logger.warning(f"[JobCapture] 卡片 {idx} 资产生成失败: {e}")
            risk_flags.append(f"资产生成失败: {e}")

        results.append({
            "job_id": job_id,
            "company_name": company,
            "job_title": title,
            "salary_text": salary,
            "city": city_val,
            "match_score": match_score,
            "custom_resume_id": custom_resume_id,
            "greetings": greetings,
            "risk_flags": risk_flags,
        })

    msg = f"共抓取 {len(results)} 个岗位"
    if failures:
        msg += f"，{len(failures)} 个失败"

    return {
        "success": len(results) > 0,
        "total": len(results),
        "jobs": results,
        "message": msg,
    }
