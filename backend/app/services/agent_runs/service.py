"""通用 Agent 任务状态、恢复、重试与列表服务。"""

import os
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models import AgentRunModel, async_session
from app.services.agent_runs.crypto import decrypt_payload, encrypt_payload


TASK_TYPE_INTERVIEW_START = "interview_start"
TASK_TYPE_INTERVIEW_TURN = "interview_turn"
TASK_TYPE_VOICE_INTERVIEW_TURN = "voice_interview_turn"
TASK_TYPE_RESUME_OPTIMIZE = "resume_optimize"
TASK_TYPE_INTERVIEW_REPORT = "interview_report"
TASK_TYPE_JOB_ASSETS = "job_assets"
ACTIVE_STATUSES = {"queued", "retrying", "running"}
TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}

TASK_DEFINITIONS: dict[str, dict] = {
    TASK_TYPE_INTERVIEW_START: {
        "title": "生成面试首题",
        "steps": (
            ("queued", "等待执行资源"),
            ("loading_context", "读取简历与面试上下文"),
            ("generating_question", "规划面试并生成首题"),
        ),
    },
    TASK_TYPE_INTERVIEW_TURN: {
        "title": "生成面试追问与反馈",
        "steps": (
            ("queued", "等待执行资源"),
            ("loading_session", "读取面试会话与上下文"),
            ("saving_answer", "记录本轮回答"),
            ("generating_response", "生成反馈与下一题"),
            ("saving_response", "保存面试进度与回复"),
        ),
    },
    TASK_TYPE_VOICE_INTERVIEW_TURN: {
        "title": "生成语音面试回复",
        "steps": (
            ("queued", "等待执行资源"),
            ("transcribing", "识别语音或读取文本"),
            ("generating_response", "生成语音面试回复"),
            ("streaming_response", "推送语音回复"),
        ),
    },
    TASK_TYPE_RESUME_OPTIMIZE: {
        "title": "优化简历",
        "steps": (
            ("queued", "等待执行资源"),
            ("preparing", "读取简历、JD 与关联面试"),
            ("optimizing", "执行简历优化流水线"),
            ("saving_result", "保存优化结果"),
        ),
    },
    TASK_TYPE_INTERVIEW_REPORT: {
        "title": "生成面试报告",
        "steps": (
            ("queued", "等待执行资源"),
            ("loading_session", "读取面试问答"),
            ("generating_profile", "生成本轮能力画像"),
            ("generating_weakness", "生成短板地图"),
            ("saving_report", "保存报告"),
        ),
    },
    TASK_TYPE_JOB_ASSETS: {
        "title": "生成岗位投递资产",
        "steps": (
            ("queued", "等待执行资源"),
            ("loading_job", "读取岗位与候选人资料"),
            ("analyzing_jd", "分析岗位匹配度"),
            ("generating_assets", "生成定制简历与招呼文案"),
            ("saving_assets", "保存岗位资产"),
        ),
    },
}


def task_queue_enabled() -> bool:
    return os.getenv("TASK_QUEUE_ENABLED", "false").lower() == "true"


def _now() -> datetime:
    return datetime.now()


def max_attempts() -> int:
    return max(1, int(os.getenv("AGENT_RUN_MAX_ATTEMPTS", "3")))


def stale_after_seconds() -> int:
    return max(60, int(os.getenv("AGENT_RUN_STALE_SECONDS", "1800")))


def get_task_definition(task_type: str) -> dict:
    return TASK_DEFINITIONS.get(task_type, {"title": task_type, "steps": (("queued", "等待执行资源"),)})


def first_running_stage(task_type: str) -> str:
    steps = get_task_definition(task_type)["steps"]
    return steps[1][0] if len(steps) > 1 else steps[0][0]


def build_task_plan(task_type: str, stage: str, status: str) -> list[dict]:
    steps = get_task_definition(task_type)["steps"]
    stage_index = next((index for index, item in enumerate(steps) if item[0] == stage), -1)
    terminal_success = status == "succeeded"
    terminal_failure = status in {"failed", "cancelled"}
    if terminal_failure and stage_index < 0:
        stage_index = 0
    plan: list[dict] = []
    for index, (step_id, title) in enumerate(steps):
        if terminal_success or index < stage_index:
            step_status = "completed"
        elif index == stage_index:
            step_status = "failed" if terminal_failure else "running"
        else:
            step_status = "pending"
        plan.append({"id": step_id, "title": title, "status": step_status})
    return plan


def build_interview_start_plan(stage: str, status: str) -> list[dict]:
    """兼容旧测试和调用。"""
    return build_task_plan(TASK_TYPE_INTERVIEW_START, stage, status)


def serialize_run(run: AgentRunModel) -> dict:
    """只返回可交给浏览器的数据，永远不回传加密载荷。"""
    definition = get_task_definition(run.task_type)
    return {
        "run_id": run.id,
        "task_type": run.task_type,
        "title": definition["title"],
        "status": run.status,
        "stage": run.stage,
        "plan": build_task_plan(run.task_type, run.stage, run.status),
        "result": run.result,
        "error_message": run.error_message,
        "attempts": run.attempts,
        "max_attempts": max_attempts(),
        "can_retry": run.status in {"failed", "cancelled"} and run.attempts < max_attempts(),
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


class AgentRunService:
    async def create_or_get(
        self,
        *,
        user_id: str,
        payload: dict,
        idempotency_key: str,
        task_type: str = TASK_TYPE_INTERVIEW_START,
    ) -> tuple[AgentRunModel, bool]:
        if task_type not in TASK_DEFINITIONS:
            raise ValueError(f"unknown task type: {task_type}")
        async with async_session() as session:
            existing = await session.scalar(
                select(AgentRunModel).where(
                    AgentRunModel.user_id == user_id,
                    AgentRunModel.task_type == task_type,
                    AgentRunModel.idempotency_key == idempotency_key,
                )
            )
            if existing:
                return existing, False

            now = _now()
            run = AgentRunModel(
                id=str(uuid.uuid4()),
                user_id=user_id,
                task_type=task_type,
                status="queued",
                stage="queued",
                idempotency_key=idempotency_key,
                payload_encrypted=encrypt_payload(payload),
                result=None,
                error_message=None,
                attempts=0,
                created_at=now,
                updated_at=now,
                started_at=None,
                finished_at=None,
            )
            session.add(run)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing = await session.scalar(
                    select(AgentRunModel).where(
                        AgentRunModel.user_id == user_id,
                        AgentRunModel.task_type == task_type,
                        AgentRunModel.idempotency_key == idempotency_key,
                    )
                )
                if existing:
                    return existing, False
                raise
            await session.refresh(run)
            return run, True

    async def get(self, run_id: str, user_id: str) -> AgentRunModel | None:
        async with async_session() as session:
            return await session.scalar(
                select(AgentRunModel).where(
                    AgentRunModel.id == run_id,
                    AgentRunModel.user_id == user_id,
                )
            )

    async def list_runs(
        self,
        user_id: str,
        *,
        status: str | None = None,
        task_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AgentRunModel], int]:
        async with async_session() as session:
            filters = [AgentRunModel.user_id == user_id]
            if status:
                filters.append(AgentRunModel.status == status)
            if task_type:
                filters.append(AgentRunModel.task_type == task_type)
            rows = await session.scalars(
                select(AgentRunModel)
                .where(*filters)
                .order_by(AgentRunModel.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            total = await session.scalar(select(func.count(AgentRunModel.id)).where(*filters))
            return list(rows), int(total or 0)

    async def claim(self, run_id: str) -> tuple[AgentRunModel, dict] | None:
        async with async_session() as session:
            run = await session.scalar(
                select(AgentRunModel).where(AgentRunModel.id == run_id).with_for_update()
            )
            if not run or run.status not in {"queued", "retrying"}:
                return None
            now = _now()
            run.status = "running"
            run.stage = first_running_stage(run.task_type)
            run.attempts += 1
            run.started_at = now
            run.finished_at = None
            run.updated_at = now
            await session.commit()
            await session.refresh(run)
            return run, decrypt_payload(run.payload_encrypted)

    async def mark_stage(self, run_id: str, stage: str) -> None:
        async with async_session() as session:
            run = await session.get(AgentRunModel, run_id, with_for_update=True)
            if not run or run.status != "running":
                return
            valid_stages = {item[0] for item in get_task_definition(run.task_type)["steps"]}
            if stage not in valid_stages:
                raise ValueError(f"invalid stage for {run.task_type}: {stage}")
            run.stage = stage
            run.updated_at = _now()
            await session.commit()

    async def touch(self, run_id: str) -> None:
        """刷新运行中心跳，避免长时间模型调用被误判为中断。"""
        async with async_session() as session:
            run = await session.get(AgentRunModel, run_id, with_for_update=True)
            if not run or run.status != "running":
                return
            run.updated_at = _now()
            await session.commit()

    async def requeue(self, run_id: str) -> None:
        async with async_session() as session:
            run = await session.get(AgentRunModel, run_id, with_for_update=True)
            if not run or run.status != "running":
                return
            run.status = "queued"
            run.stage = "queued"
            run.updated_at = _now()
            await session.commit()

    async def retry(self, run_id: str, user_id: str) -> AgentRunModel | None:
        async with async_session() as session:
            run = await session.scalar(
                select(AgentRunModel).where(
                    AgentRunModel.id == run_id,
                    AgentRunModel.user_id == user_id,
                ).with_for_update()
            )
            if not run or run.status not in {"failed", "cancelled"} or run.attempts >= max_attempts():
                return None
            run.status = "retrying"
            run.stage = "queued"
            run.result = None
            run.error_message = None
            run.finished_at = None
            run.updated_at = _now()
            await session.commit()
            await session.refresh(run)
            return run

    async def recover_stale_runs(self, user_id: str) -> list[AgentRunModel]:
        """重新投递长期未领取的任务，并恢复 Worker 中断的 running 任务。"""
        cutoff = _now() - timedelta(seconds=stale_after_seconds())
        recovered: list[AgentRunModel] = []
        async with async_session() as session:
            rows = await session.scalars(
                select(AgentRunModel)
                .where(
                    AgentRunModel.user_id == user_id,
                    AgentRunModel.status.in_(ACTIVE_STATUSES),
                    AgentRunModel.updated_at < cutoff,
                )
                .with_for_update()
            )
            now = _now()
            for run in rows:
                run.result = None
                run.finished_at = None
                run.updated_at = now
                if run.status in {"queued", "retrying"}:
                    run.status = "retrying"
                    run.stage = "queued"
                    run.error_message = "检测到任务长时间未被领取，已自动重新投递"
                    recovered.append(run)
                elif run.attempts < max_attempts():
                    run.status = "retrying"
                    run.stage = "queued"
                    run.error_message = "检测到任务执行中断，已自动恢复等待重试"
                    recovered.append(run)
                else:
                    run.status = "failed"
                    run.error_message = "任务执行中断且已达到最大尝试次数"
                    run.finished_at = now
            await session.commit()
            for run in recovered:
                await session.refresh(run)
        return recovered

    async def succeed(self, run_id: str, result: dict) -> None:
        async with async_session() as session:
            run = await session.get(AgentRunModel, run_id, with_for_update=True)
            if not run or run.status == "cancelled":
                return
            now = _now()
            run.status = "succeeded"
            run.stage = "succeeded"
            run.result = result
            run.error_message = None
            run.updated_at = now
            run.finished_at = now
            await session.commit()

    async def fail(self, run_id: str, message: str) -> None:
        async with async_session() as session:
            run = await session.get(AgentRunModel, run_id, with_for_update=True)
            if not run or run.status == "cancelled":
                return
            now = _now()
            run.status = "failed"
            run.error_message = message[:300]
            run.updated_at = now
            run.finished_at = now
            await session.commit()

    async def cancel(self, run_id: str, user_id: str) -> AgentRunModel | None:
        async with async_session() as session:
            run = await session.scalar(
                select(AgentRunModel).where(
                    AgentRunModel.id == run_id,
                    AgentRunModel.user_id == user_id,
                ).with_for_update()
            )
            if not run or run.status not in {"queued", "retrying"}:
                return None
            now = _now()
            run.status = "cancelled"
            run.stage = "cancelled"
            run.updated_at = now
            run.finished_at = now
            await session.commit()
            await session.refresh(run)
            return run
