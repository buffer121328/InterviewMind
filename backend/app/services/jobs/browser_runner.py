"""
浏览器自动化执行器

基于 Playwright 实现浏览器操作，不承载业务判断：
- 打开岗位页面
- 定位输入框
- 填入打招呼文案
- 点击发送
- 截图回传

选择器策略按优先级尝试，兼容 BOSS直聘 / 猎聘 / 拉勾 常见 DOM 结构。
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from datetime import datetime

try:
    from playwright.async_api import async_playwright
except ImportError:
    async_playwright = None

logger = logging.getLogger(__name__)


DEFAULT_BOSS_BROWSER_PROFILE_DIR = (
    Path(__file__).resolve().parents[3] / "data" / "browser_profiles" / "boss"
)
_boss_browser_lock: Optional[asyncio.Lock] = None
_boss_browser_lock_loop = None


# ============================================================================
# 选择器策略
# ============================================================================

# BOSS直聘常用选择器
BOSS_SELECTORS = {
    "chat_input": [
        "textarea[placeholder*='请输入']",
        "div[contenteditable='true']",
        "textarea.chat-input",
        ".chat-input textarea",
        "[class*='chat-input'] textarea",
        "[class*='chat-input'] [contenteditable]",
    ],
    "send_button": [
        "button:has-text('发送')",
        "button.send-btn",
        ".chat-send",
        "[class*='send-btn']",
        "button:has-text('沟通')",
        "button:has-text('立即沟通')",
    ],
    "greeting_input_popup": [
        "textarea[placeholder*='打招呼']",
        "textarea[placeholder*='介绍']",
        "div[contenteditable='true'][class*='greeting']",
    ],
}


# ============================================================================
# 浏览器会话
# ============================================================================

@dataclass
class BrowserSession:
    """浏览器会话 — 管理一次投递操作的浏览器生命周期"""

    session_id: str
    user_id: str
    url: str
    started_at: str = ""
    screenshots: List[Dict[str, str]] = None
    errors: List[str] = None

    def __post_init__(self):
        self.started_at = datetime.now().isoformat()
        self.screenshots = []
        self.errors = []


@dataclass
class BossBrowserSessionHandle:
    """统一管理 BOSS Playwright 会话与 profile 互斥锁。"""

    pw: Any
    browser: Any
    context: Any
    _lock: asyncio.Lock
    _closed: bool = False

    async def close(self) -> None:
        if self._closed:
            return
        try:
            await close_browser(self.pw, self.browser)
        finally:
            self._closed = True
            if self._lock.locked():
                self._lock.release()


# ============================================================================
# 浏览器操作
# ============================================================================

async def start_browser(
    headless: bool = False,
    profile_dir: Optional[str] = None,
) -> Tuple[Any, Any, Any]:
    """
    启动浏览器实例。
    
    Returns:
        (playwright_instance, browser, context)
    """
    if async_playwright is None:
        logger.error("[Browser] Playwright 未安装，请运行: pip install playwright && playwright install chromium")
        raise RuntimeError("Playwright 未安装")

    pw = None
    try:
        pw = await async_playwright().start()
        configured_profile = profile_dir or os.getenv("BOSS_BROWSER_PROFILE_DIR", "").strip()
        if configured_profile:
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=os.path.expanduser(configured_profile),
                headless=headless,
                viewport={"width": 1280, "height": 800},
            )
            browser = context
        else:
            browser = await pw.chromium.launch(headless=headless)
            context = await browser.new_context(viewport={"width": 1280, "height": 800})
        logger.info("[Browser] 浏览器启动成功")
        return pw, browser, context
    except Exception as e:
        if pw is not None:
            await pw.stop()
        logger.error(f"[Browser] 启动失败: {e}")
        raise


def resolve_boss_browser_profile_dir(profile_dir: Optional[str] = None) -> Path:
    """返回 BOSS 专用 profile；未配置时使用后端运行数据目录。"""
    configured = profile_dir or os.getenv("BOSS_BROWSER_PROFILE_DIR", "").strip()
    path = Path(configured).expanduser() if configured else DEFAULT_BOSS_BROWSER_PROFILE_DIR
    return path.resolve()


def _get_boss_browser_lock() -> asyncio.Lock:
    """按事件循环创建锁，兼容测试与开发服务器重载。"""
    global _boss_browser_lock, _boss_browser_lock_loop
    loop = asyncio.get_running_loop()
    if _boss_browser_lock is None or _boss_browser_lock_loop is not loop:
        _boss_browser_lock = asyncio.Lock()
        _boss_browser_lock_loop = loop
    return _boss_browser_lock


async def open_boss_browser_session(
    headless: bool = False,
    profile_dir: Optional[str] = None,
) -> BossBrowserSessionHandle:
    """打开共享登录态的 BOSS 会话，并串行化同一进程内的 profile 访问。"""
    lock = _get_boss_browser_lock()
    await lock.acquire()
    try:
        resolved_profile = resolve_boss_browser_profile_dir(profile_dir)
        resolved_profile.mkdir(parents=True, exist_ok=True)
        pw, browser, context = await start_browser(
            headless=headless,
            profile_dir=str(resolved_profile),
        )
        logger.info("[Browser] BOSS 持久化会话已启动")
        return BossBrowserSessionHandle(
            pw=pw,
            browser=browser,
            context=context,
            _lock=lock,
        )
    except Exception:
        lock.release()
        raise


async def open_job_page(context: Any, url: str) -> Any:
    """打开岗位页面"""
    page = await context.new_page()
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(2000)  # 等待动态内容加载
    logger.info(f"[Browser] 页面已打开: {url[:50]}...")
    return page


async def scrape_page_text(page: Any) -> str:
    """获取当前页面可见文本（用于岗位采集）"""
    try:
        text = await page.evaluate("""
            () => {
                const body = document.body;
                const clone = body.cloneNode(true);
                // 移除 script/style
                clone.querySelectorAll('script, style, noscript').forEach(el => el.remove());
                return clone.innerText;
            }
        """)
        return (text or "")[:5000]
    except Exception as e:
        logger.warning(f"[Browser] 提取页面文本失败: {e}")
        return ""


async def inspect_page_state(page: Any) -> Dict[str, str]:
    """识别必须停止自动点击并交给用户处理的页面状态。"""
    text = (await scrape_page_text(page)).lower()
    url = str(getattr(page, "url", "")).lower()

    if not text.strip():
        return {"status": "manual_takeover", "reason": "无法确认页面状态"}
    if (
        any(keyword in text for keyword in ("请稍候", "安全验证", "拖动滑块", "访问验证", "验证码"))
        or "verify" in url
    ):
        return {"status": "manual_takeover", "reason": "页面要求安全验证"}
    if any(keyword in text for keyword in ("登录后继续", "扫码登录", "手机号登录")) or "/login" in url:
        return {"status": "login_required", "reason": "登录状态已失效"}
    if any(keyword in text for keyword in ("职位已关闭", "职位不存在", "该职位已下线")):
        return {"status": "unavailable", "reason": "岗位已失效"}
    return {"status": "ready", "reason": ""}


async def locate_and_fill_greeting(
    page: Any,
    greeting_text: str,
    platform: str = "boss",
) -> Dict[str, Any]:
    """
    定位输入框并填入打招呼文案。
    
    选择器策略：按优先级尝试 BOSS直聘常见选择器。
    
    Returns:
        {"success": bool, "filled": bool, "selector_used": str, "error": str}
    """
    selectors = BOSS_SELECTORS["chat_input"]

    for selector in selectors:
        try:
            element = await page.wait_for_selector(selector, timeout=3000)
            if element:
                await element.click()
                await element.fill("")
                await element.type(greeting_text, delay=50)
                logger.info(f"[Browser] 文案已填入 (选择器: {selector})")
                return {
                    "success": True,
                    "filled": True,
                    "selector_used": selector,
                    "error": None,
                }
        except Exception:
            continue

    return {
        "success": False,
        "filled": False,
        "selector_used": "",
        "error": "所有选择器均无法定位输入框",
    }


async def locate_and_click_send(page: Any) -> Dict[str, Any]:
    """
    定位并点击发送按钮（不执行实际点击，仅定位验证）。
    
    Returns:
        {"success": bool, "found": bool, "selector_used": str, "element": Any}
    """
    selectors = BOSS_SELECTORS["send_button"]

    for selector in selectors:
        try:
            element = await page.wait_for_selector(selector, timeout=3000)
            if element:
                logger.info(f"[Browser] 发送按钮已定位 (选择器: {selector})")
                return {
                    "success": True,
                    "found": True,
                    "selector_used": selector,
                    "element": element,
                }
        except Exception:
            continue

    return {
        "success": False,
        "found": False,
        "selector_used": "",
        "error": "所有选择器均无法定位发送按钮",
    }


async def verify_send_result(page: Any) -> Dict[str, Any]:
    """点击后保守验证发送结果；无法确认时交给用户复核。"""
    text = (await scrape_page_text(page)).lower()
    if any(keyword in text for keyword in ("发送成功", "消息已发送")):
        return {"verified": True, "evidence": "success_message"}

    for selector in BOSS_SELECTORS["chat_input"]:
        try:
            element = await page.query_selector(selector)
            if not element:
                continue
            value = await element.input_value()
            if not value.strip():
                return {"verified": True, "evidence": "input_cleared"}
        except Exception:
            continue

    return {"verified": False, "evidence": ""}


async def take_screenshot(page: Any, label: str = "screenshot") -> str:
    """
    截图并返回 base64 编码。
    
    Returns:
        base64 编码的截图数据
    """
    import base64
    import os

    try:
        screenshot_bytes = await page.screenshot(full_page=False)
        base64_data = base64.b64encode(screenshot_bytes).decode("utf-8")

        # 可选：保存到文件
        screenshot_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "screenshots"
        )
        os.makedirs(screenshot_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{label}_{timestamp}.png"
        filepath = os.path.join(screenshot_dir, filename)
        with open(filepath, "wb") as f:
            f.write(screenshot_bytes)

        logger.info(f"[Browser] 截图已保存: {filepath}")
        return base64_data

    except Exception as e:
        logger.error(f"[Browser] 截图失败: {e}")
        return ""


async def close_browser(pw: Any, browser: Any):
    """安全关闭浏览器"""
    try:
        await browser.close()
        await pw.stop()
        logger.info("[Browser] 浏览器已关闭")
    except Exception as e:
        logger.warning(f"[Browser] 关闭浏览器异常: {e}")
