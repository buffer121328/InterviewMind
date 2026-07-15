"""
BOSS 投递执行服务（半自动发送）

执行一次投递动作的核心流程：
1. 验证用户已确认所有资产
2. 调用宿主机浏览器服务
3. 打开岗位页面 → 填入文案 → 截图预览
4. 等待用户最终确认
5. 点击发送 → 截图结果
6. 保存投递记录 + 审计日志

关键约束：发送按钮点击不立即执行，先截图让用户确认，确认后才真正点击。
"""

import hashlib
import logging
from typing import Dict, Any, Optional
from datetime import datetime

from app.services.security import safe_error_message

from .apply_approval import ApprovalError, apply_approval_registry, is_allowed_apply_url
from .boss_automation_client import BossAutomationError, get_boss_automation_client

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
    if not is_allowed_apply_url(source_url):
        return {
            "success": False,
            "message": "自动投递仅支持 BOSS 直聘官方 HTTPS 岗位链接",
            "send_ready": False,
            "send_status": "manual_takeover",
        }

    # 预览只检查额度，不占用实际发送次数。
    from .rate_limiter import check_rate, RateLimitType
    can_proceed, limit_msg = await check_rate(user_id, RateLimitType.SEND, record=False)
    if not can_proceed:
        return {"success": False, "message": limit_msg, "send_ready": False}

    try:
        result = await get_boss_automation_client().preview(source_url, greeting_text)
        approval_token = None
        approval_expires_in = None
        if result.get("success") and result.get("send_ready"):
            approval_token, approval_expires_in = await apply_approval_registry.issue(
                user_id=user_id,
                job_id=job_id,
                greeting_text=greeting_text,
                source_url=source_url,
                resume_id=resume_id,
            )
        return {
            **result,
            "approval_token": approval_token,
            "approval_expires_in": approval_expires_in,
        }
    except Exception as e:
        error_message = safe_error_message(e)
        logger.error("[ApplyService] 预览失败: %s", error_message)
        return {
            "success": False,
            "message": f"宿主机 BOSS 服务预览失败: {error_message}",
            "send_ready": False,
        }


async def execute_apply_send(
    job_id: int,
    user_id: str,
    greeting_text: str,
    resume_id: Optional[int] = None,
    approval_token: Optional[str] = None,
    confirmed: bool = False,
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

    if not confirmed:
        return {
            "success": False,
            "send_status": "pending",
            "message": "必须显式确认后才能发送",
        }
    if not approval_token:
        return {
            "success": False,
            "send_status": "pending",
            "message": "缺少预览许可，请先生成并确认预览",
        }

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
    if not is_allowed_apply_url(source_url):
        return {
            "success": False,
            "send_status": "manual_takeover",
            "message": "自动投递仅支持 BOSS 直聘官方 HTTPS 岗位链接",
        }
    if job.get("status") == "applied":
        return {
            "success": False,
            "send_status": "sent",
            "message": "该岗位已投递，已阻止重复发送",
        }

    try:
        await apply_approval_registry.consume(
            approval_token,
            user_id=user_id,
            job_id=job_id,
            greeting_text=greeting_text,
            source_url=source_url,
            resume_id=resume_id,
        )
    except ApprovalError as exc:
        return {"success": False, "send_status": "pending", "message": str(exc)}

    from .rate_limiter import check_rate, RateLimitType
    can_proceed, limit_msg = await check_rate(user_id, RateLimitType.SEND)
    if not can_proceed:
        return {"success": False, "send_status": "pending", "message": limit_msg}

    previous_status = job.get("status") or "pending"
    if not await repo.claim_for_application(job_id, user_id):
        return {
            "success": False,
            "send_status": "pending",
            "message": "该岗位正在投递或已处理，已阻止重复发送",
        }

    try:
        result = await get_boss_automation_client().send(source_url, greeting_text)
        steps = result.get("steps", [])
        screenshot_b64 = result.get("screenshot_base64", "")
        if not result.get("success"):
            clicked = bool(result.get("clicked"))
            next_status = "manual_takeover" if clicked else previous_status
            await repo.update_status(job_id, user_id, next_status)
            from .rate_limiter import record_failure
            await record_failure(user_id)
            await _save_application_record(
                user_id=user_id,
                job=job,
                greeting_text=greeting_text,
                resume_id=resume_id,
                send_status="failed",
                steps=steps,
                error=result.get("message", "发送失败"),
                screenshot_base64=screenshot_b64,
            )
            return result

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

        from .rate_limiter import record_success
        await record_success(user_id)

        return {
            "success": True,
            "send_status": "sent",
            "message": "发送成功",
            "screenshot_base64": screenshot_b64,
            "steps": steps,
        }

    except Exception as e:
        error_message = safe_error_message(e)
        logger.error("[ApplyService] 发送失败: %s", error_message)
        from .rate_limiter import record_failure
        await record_failure(user_id)
        ambiguous = isinstance(e, BossAutomationError) and e.request_may_have_run
        await repo.update_status(
            job_id,
            user_id,
            "manual_takeover" if ambiguous else previous_status,
        )
        steps = [{"step": "host_rpc", "status": "failed", "detail": error_message}]
        steps.append({"step": "error", "status": "failed", "detail": error_message})
        await _save_application_record(
            user_id=user_id,
            job=job,
            greeting_text=greeting_text,
            resume_id=resume_id,
            send_status="failed",
            steps=steps,
            error=error_message,
            screenshot_base64="",
        )

        return {
            "success": False,
            "send_status": "manual_takeover" if ambiguous else "failed",
            "message": (
                "宿主机服务通信中断，发送状态可能不明确，请人工复核，勿重复发送"
                if ambiguous
                else f"发送失败: {error_message}"
            ),
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
                f"打招呼文案长度: {len(greeting_text)}\n"
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
                    "greeting_digest": hashlib.sha256(greeting_text.encode()).hexdigest(),
                    "greeting_length": len(greeting_text),
                    "resume_id": resume_id,
                    "automation_steps": steps,
                    "error": error,
                    "screenshot_included": bool(screenshot_base64),
                },
            ),
        )

        logger.info(f"[ApplyService] 投递记录已保存: app_id={app.id}, status={send_status}")
    except Exception as e:
        logger.error("[ApplyService] 保存投递记录失败: %s", safe_error_message(e))
