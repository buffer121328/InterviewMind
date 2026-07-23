"""
审计日志

记录每次自动化操作的完整链路：
- 谁触发了操作 (user_id)
- 基于哪个岗位 (job_id)
- 使用了哪份简历 (resume_id)
- 使用了哪条文案 (greeting_text)
- 是否实际发送 (send_confirmed)
- 自动化步骤结果 (step_results)
- 失败原因和截图
"""

import logging
import json
from typing import Dict, Any, List, Optional
from datetime import datetime
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


@dataclass
class AuditStep:
    """单个自动化步骤"""
    step: str           # 步骤名
    status: str         # success / failed / skipped
    detail: str = ""    # 详细信息
    error: str = ""     # 错误信息
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class AuditRecord:
    """单次自动化操作的完整审计记录"""
    record_id: str
    user_id: str
    action: str                     # capture / generate_assets / preview / send / cancel
    job_id: Optional[int] = None
    resume_id: Optional[int] = None
    greeting_text: str = ""
    send_confirmed: bool = False
    send_status: str = ""            # pending / sent / failed / manual_takeover
    steps: List[AuditStep] = field(default_factory=list)
    error: str = ""
    screenshot_included: bool = False
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ============================================================================
# 内存存储
# ============================================================================

# {user_id: [AuditRecord, ...]}
_audit_store: Dict[str, List[AuditRecord]] = {}


# ============================================================================
# 公开接口
# ============================================================================

async def log_audit(record: AuditRecord):
    """记录一条审计日志"""
    user_records = _audit_store.setdefault(record.user_id, [])
    user_records.append(record)

    # 打印关键信息
    step_summary = " → ".join(
        f"{s.step}({s.status})" for s in record.steps
    )
    logger.info(
        f"[Audit] user={record.user_id} action={record.action} "
        f"job={record.job_id} send={record.send_status} "
        f"steps=[{step_summary}]"
    )


async def get_audit_logs(
    user_id: str,
    action: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """查询审计日志"""
    records = _audit_store.get(user_id, [])

    if action:
        records = [r for r in records if r.action == action]

    # 按时间倒序
    records = sorted(records, key=lambda r: r.created_at, reverse=True)
    records = records[:limit]

    return [asdict(r) for r in records]


async def get_last_audit(
    user_id: str,
    action: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """获取最近一条审计记录"""
    records = _audit_store.get(user_id, [])
    if action:
        records = [r for r in records if r.action == action]

    if not records:
        return None

    latest = max(records, key=lambda r: r.created_at)
    return asdict(latest)


async def create_audit_record(
    user_id: str,
    action: str,
    job_id: Optional[int] = None,
    resume_id: Optional[int] = None,
    greeting_text: str = "",
    send_confirmed: bool = False,
    send_status: str = "",
    steps: List[Dict[str, str]] = None,
    error: str = "",
    screenshot_included: bool = False,
) -> AuditRecord:
    """创建审计记录并立即落库"""
    import uuid

    audit_steps = []
    if steps:
        for s in steps:
            audit_steps.append(AuditStep(
                step=s.get("step", ""),
                status=s.get("status", "unknown"),
                detail=s.get("detail", ""),
                error=s.get("error", ""),
            ))

    record = AuditRecord(
        record_id=str(uuid.uuid4()),
        user_id=user_id,
        action=action,
        job_id=job_id,
        resume_id=resume_id,
        greeting_text=greeting_text,
        send_confirmed=send_confirmed,
        send_status=send_status,
        steps=audit_steps,
        error=error,
        screenshot_included=screenshot_included,
    )

    await log_audit(record)
    return record
