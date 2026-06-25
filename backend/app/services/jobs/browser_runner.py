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

import logging
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


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


# ============================================================================
# 浏览器操作
# ============================================================================

async def start_browser(headless: bool = False) -> Tuple[Any, Any, Any]:
    """
    启动浏览器实例。
    
    Returns:
        (playwright_instance, browser, context)
    """
    try:
        from playwright.async_api import async_playwright

        pw = await async_playwright().start()
        browser = await pw.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        logger.info("[Browser] 浏览器启动成功")
        return pw, browser, context
    except ImportError:
        logger.error("[Browser] Playwright 未安装，请运行: pip install playwright && playwright install chromium")
        raise RuntimeError("Playwright 未安装")
    except Exception as e:
        logger.error(f"[Browser] 启动失败: {e}")
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
