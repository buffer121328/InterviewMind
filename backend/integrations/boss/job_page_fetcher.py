"""Page-fetching helpers for job capture workflows."""

import asyncio
import logging
import os
import platform as _platform

from app.security.security import safe_error_message
from app.security.url_security import validate_outbound_url

logger = logging.getLogger(__name__)


async def _fetch_via_existing_chrome(url: str) -> str:
    """通过用户已打开的 Chrome 读取已存在 tab 的页面文本，仅 macOS 可用。"""
    if _platform.system() != "Darwin":
        return ""

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
            "osascript",
            "-e",
            script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
        text = stdout.decode("utf-8", errors="ignore").strip()
        if text and len(text) > 200 and "请稍候" not in text:
            return text
        return ""
    except Exception as exc:
        logger.debug("[JobCapture] AppleScript Chrome 读取失败: %s", exc)
        return ""


async def _fetch_page_text_browser(
    url: str,
    cookies: list | None = None,
    headless: bool = True,
    manual_wait_seconds: int = 90,
) -> str:
    """通过宿主机 BOSS 服务的持久化 Playwright profile 抓取页面文本。"""
    try:
        from integrations.boss.automation_client import get_boss_automation_client

        if cookies:
            logger.warning("[JobCapture] 远程 BOSS 服务不接收 Cookie，改用宿主机持久化 profile")
        result = await get_boss_automation_client().scrape(
            url,
            headless=headless,
            manual_wait_seconds=manual_wait_seconds,
        )
        text = result.get("text", "") if result.get("success") else ""
        if text:
            logger.info("[JobCapture] 宿主机浏览器抓取成功, %s 字符", len(text))
        return text
    except Exception as exc:
        logger.warning("[JobCapture] 宿主机浏览器抓取失败: %s", safe_error_message(exc))
        return ""


async def _fetch_page_text(url: str) -> str:
    """通过 HTTP 抓取页面文本（降级方案，优先用浏览器）。"""
    try:
        import httpx
        import re
        from urllib.parse import urljoin

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        current_url = url
        max_response_bytes = max(64 * 1024, int(os.getenv("JOB_CAPTURE_MAX_RESPONSE_BYTES", str(2 * 1024 * 1024))))
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            for _ in range(6):
                await asyncio.to_thread(validate_outbound_url, current_url, allow_private=False)
                async with client.stream("GET", current_url, headers=headers) as resp:
                    if resp.is_redirect:
                        location = resp.headers.get("location")
                        if not location:
                            return ""
                        current_url = urljoin(current_url, location)
                        continue
                    resp.raise_for_status()
                    body = bytearray()
                    async for chunk in resp.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > max_response_bytes:
                            raise ValueError("岗位页面响应内容过大")
                    encoding = resp.encoding or "utf-8"
                    html = body.decode(encoding, errors="replace")
                    break
            else:
                raise ValueError("岗位链接重定向次数过多")

            text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
            text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            return text[:5000]
    except Exception as exc:
        logger.warning("[JobCapture] HTTP 抓取失败: %s", exc)
        return ""


async def _open_and_read_in_chrome(
    url: str,
    wait_seconds: int = 8,
    wait_for_user_captcha: bool = False,
    captcha_timeout: int = 120,
) -> str:
    """让用户已打开的 Chrome 新开 tab 访问 URL 并读取 body innerText，仅 macOS 可用。"""
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
                "osascript",
                "-e",
                script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return stdout.decode("utf-8", errors="ignore").strip()
        except Exception as exc:
            logger.warning("[JobCapture] AppleScript 调用失败: %s", exc)
            return ""

    text = await _run_applescript(_build_script(url, wait_seconds), wait_seconds + 20)
    if not wait_for_user_captcha:
        return text

    is_captcha = bool(text) and ("请稍候" in text or "安全验证" in text or "verify.html" in text or len(text) < 200)
    if not is_captcha:
        return text

    logger.info("[JobCapture] 检测到反爬验证页，等待用户在 Chrome 中手动完成验证（最多 %s秒）...", captcha_timeout)

    waited = 0
    recheck_script = _build_recheck_script()
    while waited < captcha_timeout:
        await asyncio.sleep(5)
        waited += 5
        text = await _run_applescript(recheck_script, 15)
        if not text:
            continue
        if "请稍候" in text or "安全验证" in text or "verify.html" in text:
            continue
        if len(text) < 200:
            continue
        logger.info("[JobCapture] 用户已完成验证（耗时 %s 秒），抓到 %s 字符", waited, len(text))
        return text

    logger.warning("[JobCapture] 用户验证超时（%s秒），放弃抓取", captcha_timeout)
    return ""
