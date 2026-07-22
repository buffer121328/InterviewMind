"""宿主机 BOSS 浏览器操作。

只负责 Playwright 页面交互，不访问数据库、不签发人工审批许可。
"""

from __future__ import annotations

import logging
from typing import Any

from .boss_security import is_allowed_apply_url
from .browser_runner import (
    BOSS_SELECTORS,
    inspect_page_state,
    locate_and_click_send,
    locate_and_fill_greeting,
    open_boss_browser_session,
    open_job_page,
    scrape_page_text,
    take_screenshot,
    verify_send_result,
)

logger = logging.getLogger(__name__)


def _require_allowed_url(source_url: str) -> None:
    """校验 `allowed url`。

    Args:
        source_url: source URL。
    """
    if not is_allowed_apply_url(source_url):
        raise ValueError("仅允许访问 BOSS 直聘官方 HTTPS 链接")


async def scrape_boss_page(
    source_url: str,
    *,
    headless: bool = False,
    manual_wait_seconds: int = 90,
) -> dict[str, Any]:
    """使用宿主机持久化 profile 读取页面文本。"""

    _require_allowed_url(source_url)
    session = await open_boss_browser_session(headless=headless)
    try:
        page = await open_job_page(session.context, source_url)
        if not headless:
            state = await inspect_page_state(page)
            if state["status"] != "ready":
                logger.info(
                    "[BossHost] 等待用户完成登录或验证（最多 %s 秒）",
                    manual_wait_seconds,
                )
                try:
                    await page.wait_for_function(
                        """() => {
                            const t = document.body?.innerText || '';
                            const blocked = /请稍候|安全验证|拖动滑块|扫码登录|手机号登录/.test(t);
                            return t.length > 200 && !blocked && !location.pathname.includes('/login');
                        }""",
                        timeout=manual_wait_seconds * 1000,
                    )
                except Exception:
                    logger.warning("[BossHost] 等待用户登录或验证超时")

        text = await scrape_page_text(page)
        await page.close()
        return {"success": bool(text), "text": text}
    finally:
        await session.close()


async def preview_boss_application(
    source_url: str,
    greeting_text: str,
) -> dict[str, Any]:
    """填入问候语并返回截图；绝不点击发送按钮。"""

    _require_allowed_url(source_url)
    session = await open_boss_browser_session(headless=False)
    try:
        page = await open_job_page(session.context, source_url)
        state = await inspect_page_state(page)
        if state["status"] != "ready":
            return {
                "success": False,
                "message": state["reason"],
                "send_ready": False,
                "send_status": state["status"],
            }

        await take_screenshot(page, "page_opened")
        fill_result = await locate_and_fill_greeting(page, greeting_text)
        if not fill_result.get("filled"):
            for selector in BOSS_SELECTORS.get("greeting_input_popup", []):
                try:
                    element = await page.wait_for_selector(selector, timeout=3000)
                    if element:
                        await element.click()
                        await element.fill(greeting_text)
                        fill_result = {
                            "success": True,
                            "filled": True,
                            "selector_used": selector,
                            "error": None,
                        }
                        break
                except Exception:
                    continue

        if not fill_result.get("filled"):
            return {
                "success": False,
                "message": f"无法定位输入框: {fill_result.get('error')}",
                "send_ready": False,
            }

        screenshot = await take_screenshot(page, "greeting_filled")
        send_result = await locate_and_click_send(page)
        return {
            "success": True,
            "screenshot_base64": screenshot,
            "message": "预览已生成，请确认后发送",
            "send_ready": bool(send_result.get("found")),
            "fill_info": fill_result,
        }
    finally:
        await session.close()


async def send_boss_application(
    source_url: str,
    greeting_text: str,
) -> dict[str, Any]:
    """执行发送，并明确报告点击是否已经发生。"""

    _require_allowed_url(source_url)
    steps: list[dict[str, str]] = []
    clicked = False
    session = await open_boss_browser_session(headless=False)
    try:
        steps.append({"step": "start_browser", "status": "success"})
        page = await open_job_page(session.context, source_url)
        steps.append({"step": "open_page", "status": "success"})

        state = await inspect_page_state(page)
        if state["status"] != "ready":
            steps.append(
                {"step": "page_guard", "status": "blocked", "detail": state["reason"]}
            )
            return {
                "success": False,
                "send_status": state["status"],
                "message": state["reason"],
                "clicked": False,
                "steps": steps,
            }

        fill_result = await locate_and_fill_greeting(page, greeting_text)
        steps.append(
            {
                "step": "fill_greeting",
                "status": "success" if fill_result.get("filled") else "failed",
                "detail": fill_result.get("selector_used", ""),
            }
        )
        if not fill_result.get("filled"):
            raise RuntimeError(f"填入失败: {fill_result.get('error')}")

        send_result = await locate_and_click_send(page)
        element = send_result.get("element")
        if not send_result.get("found") or element is None:
            steps.append(
                {
                    "step": "click_send",
                    "status": "failed",
                    "detail": send_result.get("error", "按钮未找到"),
                }
            )
            raise RuntimeError("发送按钮未找到")

        await element.click()
        clicked = True
        await page.wait_for_timeout(2000)
        steps.append({"step": "click_send", "status": "success"})

        verification = await verify_send_result(page)
        steps.append(
            {
                "step": "verify_send",
                "status": "success" if verification["verified"] else "unverified",
                "detail": verification["evidence"],
            }
        )
        if not verification["verified"]:
            screenshot = await take_screenshot(page, "send_unverified")
            return {
                "success": False,
                "send_status": "manual_takeover",
                "message": "已执行点击但无法确认发送结果，请根据截图人工复核，勿重复发送",
                "screenshot_base64": screenshot,
                "clicked": True,
                "steps": steps,
            }

        screenshot = await take_screenshot(page, "send_result")
        steps.append({"step": "screenshot", "status": "success"})
        return {
            "success": True,
            "send_status": "sent",
            "message": "发送成功",
            "screenshot_base64": screenshot,
            "clicked": True,
            "steps": steps,
        }
    except Exception as exc:
        steps.append({"step": "error", "status": "failed", "detail": str(exc)[:200]})
        return {
            "success": False,
            "send_status": "manual_takeover" if clicked else "failed",
            "message": (
                "发送动作后状态不明确，请人工复核，勿重复发送"
                if clicked
                else f"发送失败: {str(exc)[:200]}"
            ),
            "clicked": clicked,
            "steps": steps,
        }
    finally:
        await session.close()
