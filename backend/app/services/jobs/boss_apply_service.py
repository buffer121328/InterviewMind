"""
BOSS 投递执行服务（半自动发送）

执行一次投递动作的核心流程：
1. 验证用户已确认所有资产
2. 启动浏览器会话
3. 打开岗位页面 → 填入文案 → 截图预览
4. 等待用户最终确认
5. 点击发送 → 截图结果
6. 保存投递记录 + 审计日志

关键约束：发送按钮点击不立即执行，先截图让用户确认，确认后才真正点击。
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime

from .browser_runner import (
    start_browser,
    open_job_page,
    locate_and_fill_greeting,
    locate_and_click_send,
    take_screenshot,
    close_browser,
)

logger = logging.getLogger(__name__)


async def execute_apply_preview(
    job_id: int,
    user_id: str,
    greeting_text: str,
    resume_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    投递预览：打开页面 → 填入文案 → 截图 → 返回预览（不发送）。
    
    Args:
        job_id: 岗位 ID
        user_id: 用户 ID
        greeting_text: 要填入的打招呼文案
        resume_id: 可选，要附加的简历 ID
        
    Returns:
        {
            "success": bool,
            "screenshot_base64": str,
            "message": str,
            "send_ready": bool,  # 已准备好可以发送
        }
    """
    from app.repositories.jobs.job_capture_repo import get_job_capture_repo

    # 获取岗位信息
    repo = get_job_capture_repo()
    job = await repo.get_job(job_id, user_id)
    if not job:
        return {"success": False, "message": "岗位不存在", "send_ready": False}

    source_url = job.get("source_url", "")
    if not source_url:
        return {
            "success": False,
            "message": "该岗位无来源链接，无法自动投递，请手动操作",
            "send_ready": False,
        }

    # 频率检查
    from .rate_limiter import check_rate, RateLimitType
    can_proceed, limit_msg = await check_rate(user_id, RateLimitType.SEND)
    if not can_proceed:
        return {"success": False, "message": limit_msg, "send_ready": False}

    pw = None
    browser = None

    try:
        # 启动浏览器
        pw, browser, context = await start_browser(headless=False)

        # 打开岗位页面
        page = await open_job_page(context, source_url)

        # 截图 - 打开页面后
        await take_screenshot(page, "page_opened")

        # 定位并填入打招呼文案
        fill_result = await locate_and_fill_greeting(page, greeting_text)

        if not fill_result.get("filled"):
            # 尝试在弹窗中填入（BOSS直聘的打招呼弹窗）
            from .browser_runner import BOSS_SELECTORS
            popup_selectors = BOSS_SELECTORS.get("greeting_input_popup", [])
            for sel in popup_selectors:
                try:
                    element = await page.wait_for_selector(sel, timeout=3000)
                    if element:
                        await element.click()
                        await element.fill(greeting_text)
                        fill_result = {"success": True, "filled": True, "selector_used": sel, "error": None}
                        break
                except Exception:
                    continue

        if not fill_result.get("filled"):
            await close_browser(pw, browser)
            return {
                "success": False,
                "message": f"无法定位输入框: {fill_result.get('error')}",
                "send_ready": False,
            }

        # 截图 - 填入文案后
        screenshot_b64 = await take_screenshot(page, "greeting_filled")

        # 检查发送按钮是否可用
        send_result = await locate_and_click_send(page)

        # 关闭浏览器（预览阶段不保持连接）
        await close_browser(pw, browser)

        return {
            "success": True,
            "screenshot_base64": screenshot_b64,
            "message": "预览已生成，请确认后发送",
            "send_ready": send_result.get("found", False),
            "fill_info": fill_result,
        }

    except ImportError:
        return {
            "success": False,
            "message": "浏览器自动化未安装 (playwright)。请安装后重试。",
            "send_ready": False,
        }
    except Exception as e:
        logger.error(f"[ApplyService] 预览失败: {e}", exc_info=True)
        if pw and browser:
            await close_browser(pw, browser)
        return {
            "success": False,
            "message": f"预览失败: {e}",
            "send_ready": False,
        }


async def execute_apply_send(
    job_id: int,
    user_id: str,
    greeting_text: str,
    resume_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    确认发送：用户确认后，打开页面 → 填入 → 点击发送 → 截图结果。
    
    Args:
        job_id: 岗位 ID
        user_id: 用户 ID
        greeting_text: 打招呼文案
        resume_id: 简历 ID
        
    Returns:
        {"success": bool, "send_status": str, "message": str, "screenshot_base64": str}
    """
    from app.repositories.jobs.job_capture_repo import get_job_capture_repo

    repo = get_job_capture_repo()
    job = await repo.get_job(job_id, user_id)
    if not job:
        return {"success": False, "send_status": "failed", "message": "岗位不存在"}

    source_url = job.get("source_url", "")
    if not source_url:
        return {
            "success": False,
            "send_status": "manual_takeover",
            "message": "无来源链接，需手动投递",
        }

    pw = None
    browser = None
    steps = []

    try:
        # 启动浏览器
        pw, browser, context = await start_browser(headless=False)
        steps.append({"step": "start_browser", "status": "success"})

        # 打开页面
        page = await open_job_page(context, source_url)
        steps.append({"step": "open_page", "status": "success"})

        # 填入文案
        fill_result = await locate_and_fill_greeting(page, greeting_text)
        steps.append({
            "step": "fill_greeting",
            "status": "success" if fill_result.get("filled") else "failed",
            "detail": fill_result.get("selector_used", ""),
        })

        if not fill_result.get("filled"):
            raise RuntimeError(f"填入失败: {fill_result.get('error')}")

        # 点击发送
        send_result = await locate_and_click_send(page)
        if send_result.get("found") and send_result.get("element"):
            await send_result["element"].click()
            await page.wait_for_timeout(2000)  # 等待发送完成
            steps.append({"step": "click_send", "status": "success"})
        else:
            steps.append({
                "step": "click_send",
                "status": "failed",
                "detail": send_result.get("error", "按钮未找到"),
            })
            raise RuntimeError("发送按钮未找到")

        # 截图结果
        screenshot_b64 = await take_screenshot(page, "send_result")
        steps.append({"step": "screenshot", "status": "success"})

        # 关闭浏览器
        await close_browser(pw, browser)

        # ================================================================
        # 保存投递记录
        # ================================================================
        await _save_application_record(
            user_id=user_id,
            job=job,
            greeting_text=greeting_text,
            resume_id=resume_id,
            send_status="sent",
            steps=steps,
            screenshot_base64=screenshot_b64,
        )

        # 更新岗位状态
        await repo.update_status(job_id, user_id, "applied")

        return {
            "success": True,
            "send_status": "sent",
            "message": "发送成功",
            "screenshot_base64": screenshot_b64,
            "steps": steps,
        }

    except ImportError:
        return {
            "success": False,
            "send_status": "failed",
            "message": "浏览器自动化未安装",
        }
    except Exception as e:
        logger.error(f"[ApplyService] 发送失败: {e}", exc_info=True)

        # 失败截图
        if pw and browser:
            try:
                screenshot_b64 = await take_screenshot(page if 'page' in dir() else None, "error")
            except Exception:
                screenshot_b64 = ""

            await close_browser(pw, browser)

        steps.append({"step": "error", "status": "failed", "detail": str(e)})

        # 保存失败记录
        await _save_application_record(
            user_id=user_id,
            job=job,
            greeting_text=greeting_text,
            resume_id=resume_id,
            send_status="failed",
            steps=steps,
            error=str(e),
            screenshot_base64="",
        )

        return {
            "success": False,
            "send_status": "failed",
            "message": f"发送失败: {e}",
            "steps": steps,
        }


async def _save_application_record(
    user_id: str,
    job: dict,
    greeting_text: str,
    resume_id: Optional[int],
    send_status: str,
    steps: list,
    screenshot_base64: str = "",
    error: str = "",
):
    """保存投递记录到 Application 表"""
    try:
        from app.repositories.application.job_application_repo import job_application_repo
        from app.schemas.job_application import ApplicationCreateRequest

        # 创建 Application
        req = ApplicationCreateRequest(
            company_name=job.get("company_name", ""),
            job_title=job.get("job_title", ""),
            job_description=job.get("job_description", ""),
            channel=job.get("platform", "boss"),
            generated_resume_id=resume_id,
            latest_status="applied" if send_status == "sent" else "saved",
            notes=(
                f"打招呼文案: {greeting_text[:50]}...\n"
                f"来源: {job.get('source_url', '')}\n"
                f"发送状态: {send_status}\n"
                + (f"错误: {error}" if error else "")
            ),
        )
        app = await job_application_repo.create_application(user_id, req)

        # 添加事件
        from app.repositories.application.application_event_repo import application_event_repo
        from app.schemas.job_application import EventCreateRequest

        await application_event_repo.add_event(
            application_id=app.id,
            request=EventCreateRequest(
                event_type="applied" if send_status == "sent" else "note",
                event_data={
                    "send_status": send_status,
                    "greeting_used": greeting_text,
                    "resume_id": resume_id,
                    "automation_steps": steps,
                    "error": error,
                    "screenshot_included": bool(screenshot_base64),
                },
            ),
        )

        logger.info(f"[ApplyService] 投递记录已保存: app_id={app.id}, status={send_status}")
    except Exception as e:
        logger.error(f"[ApplyService] 保存投递记录失败: {e}")
