"""
AgentMemoryService - mem0 长期记忆服务

已知超限：职责单一（mem0 封装），暂不拆分。

对业务暴露统一接口，隐藏 mem0 返回结构差异。
"""

import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import Any, Optional

from app.config import get_settings
from app.domain.memory import canonicalize_memory_records, normalize_memory_text
from observability import record_external_io_event
from observability.runtime_events import (
    ExternalIOObservationEvent,
    new_runtime_event_id,
)

from .config import (
    get_mem0_config,
    get_mem0_retention_days,
    get_mem0_search_limit,
)
from .lifecycle import (
    ConsolidationAction,
    LifecycleAction,
    MemoryRetentionClass,
    build_historical_consolidation_prompt,
    build_incremental_lifecycle_prompt,
    extract_result_records,
    lifecycle_counts,
    parse_historical_plan,
    parse_incremental_plan,
    public_operation,
)
from .retention import (
    CleanupAction,
    fail_closed_cleanup_plan,
    get_memory_retention_store,
    plan_cleanup,
    public_cleanup_decision,
)

logger = logging.getLogger(__name__)

INTERVIEW_MEMORY_EXTRACTION_INSTRUCTIONS = """
Long-term memory is a compact reusable candidate profile, not a transcript summary.
Extract only explicit, durable user-authored information that is likely to remain useful
across future interview sessions. Prefer no memory when uncertain and at most two candidates
from one turn.

Eligible categories:
- identity/education or stable work history;
- one canonical summary per named project or work experience;
- stable technical stack or verified capability;
- explicit career direction, durable preference, constraint, or long-term goal;
- a weakness only when the user explicitly identifies it as recurring.

Never extract assistant-authored facts, scores, strengths, feedback, coaching advice,
recommended answer structures, temporary interview performance, generic lessons,
hypothetical examples, acknowledgements, or component-level project details that belong
inside an existing project summary. Do not infer personality or durable weaknesses from one
answer. When the user adds another detail about an existing project/stack/goal, produce a
candidate suitable for consolidating that canonical topic rather than a standalone fragment.
""".strip()

# mem0 upstream enables anonymous PostHog telemetry by default.  Keep this
# product's memory runtime private/offline unless an operator explicitly opts in
# before importing this module.
os.environ.setdefault("MEM0_TELEMETRY", "False")

# 全局单例
_agent_memory_service: Optional["AgentMemoryService"] = None
_agent_memory_services: dict[str, "AgentMemoryService"] = {}


async def _run_mem0_call(
    function: Any,
    *args: Any,
    timeout: float,
    **kwargs: Any,
) -> Any:
    """Run one synchronous mem0 operation with an independent external-I/O timeout."""
    return await asyncio.wait_for(
        asyncio.to_thread(function, *args, **kwargs),
        timeout=timeout,
    )


def _external_error_category(exc: BaseException) -> str:
    """Distinguish external dependency timeout from other degraded I/O failures."""
    return "external_io_timeout" if isinstance(exc, TimeoutError) else "external_io_error"


def _record_mem0_event(
    *,
    operation: str,
    call_id: str,
    status: str,
    started_at: float,
    item_count: int | None = None,
    result_count: int | None = None,
    error: BaseException | None = None,
) -> None:
    """记录 mem0 的安全外部 IO 摘要，不上传记忆正文、用户 ID 或过滤器。"""

    record_external_io_event(
        ExternalIOObservationEvent(
            event_type=f"external_io.{status}",
            operation=operation,
            status=status,
            call_id=call_id,
            dependency="mem0",
            duration_ms=max(0, int((perf_counter() - started_at) * 1000)),
            item_count=item_count,
            result_count=result_count,
            error_type=type(error).__name__ if error else None,
            error_category=_external_error_category(error) if error else None,
        )
    )




def _memory_config_cache_key(config: Optional[dict[str, Any]]) -> str:
    """为 mem0 配置生成不泄露明文 key 的缓存键。"""
    if config is None:
        return "disabled"

    def scrub(value: Any) -> Any:
        """递归移除记忆配置中的密钥类字段，只用于生成缓存指纹，不得用于实际 mem0 连接。"""
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key, item in value.items():
                if key == "api_key" and isinstance(item, str):
                    result[key] = hashlib.sha256(item.encode("utf-8")).hexdigest()
                else:
                    result[key] = scrub(item)
            return result
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return value

    payload = json.dumps(scrub(config), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _retention_metadata() -> dict:
    """生成记忆保留期限和到期策略元数据，供清理任务和审计使用。"""
    retention_days = get_mem0_retention_days()
    expires_at = datetime.now(timezone.utc) + timedelta(days=retention_days)
    return {
        "retention_days": retention_days,
        "expires_at": expires_at.isoformat(),
        "delete_sync_policy": "mem0_delete_by_user_or_expiry",
    }


def _retention_class_metadata(retention_class: MemoryRetentionClass) -> dict[str, Any]:
    """Build non-content metadata used by gradual cleanup policies."""

    now = datetime.now(timezone.utc)
    settings = get_settings()
    if retention_class is MemoryRetentionClass.CORE:
        return {
            "retention_class": retention_class.value,
            "retention_policy": "protected_until_superseded_or_manual_delete",
            "retention_days": None,
            "expires_at": None,
            "last_confirmed_at": now.isoformat(),
        }
    retention_days = (
        settings.memory_retention_durable_min_age_days
        if retention_class is MemoryRetentionClass.DURABLE
        else settings.memory_retention_transient_min_age_days
    )
    return {
        "retention_class": retention_class.value,
        "retention_policy": "two_stage_decay",
        "retention_days": retention_days,
        "expires_at": (now + timedelta(days=retention_days)).isoformat(),
        "last_confirmed_at": now.isoformat(),
    }


class AgentMemoryService:
    """应用/基础设施协作者，负责 `AgentMemoryService` 的职责；依赖通过构造或模块边界注入，外部调用、状态持久化和安全校验不向调用方隐藏。
    mem0 长期记忆服务

    提供统一的记忆管理接口，支持：
    - search_memories: 语义检索长期记忆
    - add_interaction: 添加对话交互记忆
    - add_summary_memory: 添加面试总结记忆
    - add_memory: 用户主动添加原始记忆
    - update_memory: 用户主动修改记忆
    - get_all: 获取用户全部记忆
    - history: 获取记忆变更历史
    - delete: 删除记忆
    """

    def __init__(self, config: dict | None):
        """
        初始化 mem0 客户端

        Args:
            config: mem0 配置字典
        """
        self._config = config
        self._memory = None
        self._enabled = config is not None
        self._initialization_error: str | None = None

    async def initialize(self) -> bool:
        """Initialize the mem0 client and return whether it is ready for requests."""
        if not self._enabled:
            logger.info("AgentMemoryService 已禁用")
            return False

        try:
            from mem0 import Memory

            # mem0 的 Memory 是同步的，但我们在异步方法中使用
            # 用配置信息创建一个 mem0 Memory 对象，这是工厂方法
            self._memory = await asyncio.to_thread(
                Memory.from_config,
                self._config
            )
            self._initialization_error = None
            logger.info("✓ AgentMemoryService 初始化成功")
            return True
        except Exception as exc:
            logger.error("✗ AgentMemoryService 初始化失败: %s", type(exc).__name__)
            self._enabled = False
            self._memory = None
            self._initialization_error = type(exc).__name__
            return False

    @property
    # property将一个方法转换成属性，让你可以像访问属性一样调用方法
    def is_enabled(self) -> bool:
        """检查服务是否启用"""
        return self._enabled and self._memory is not None

    @property
    def initialization_error(self) -> str | None:
        """Return only the safe exception type from the latest initialization attempt."""
        return self._initialization_error

    async def search_memories(
        self,
        *,
        user_id: str,
        query: str,
        limit: Optional[int] = None,
        memory_types: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        检索长期记忆

        Args:
            user_id: 用户 ID
            query: 搜索查询
            limit: 返回结果数量限制
            memory_types: 过滤的记忆类型列表

        Returns:
            list[dict]: 记忆列表，每条包含 id, memory, metadata 等
        """
        if not self.is_enabled:
            return []

        started_at = perf_counter()
        call_id = new_runtime_event_id("mem0_search")
        _record_mem0_event(
            operation="mem0.search", call_id=call_id, status="started", started_at=started_at
        )
        try:
            search_limit = limit or get_mem0_search_limit()

            # mem0 的 search 是同步的，放到线程池执行
            result = await _run_mem0_call(
                self._memory.search,
                query=query,
                top_k=search_limit,
                filters={"user_id": user_id},
                timeout=get_settings().mem0_search_timeout_seconds,
            )

            # mem0 返回格式可能是 {"results": [...]} 或直接是列表
            memories = []
            if isinstance(result, dict):
                memories = result.get("results", [])
            elif isinstance(result, list):
                memories = result

            # 按 memory_types 过滤
            if memory_types:
                memories = [
                    m for m in memories
                    if m.get("metadata", {}).get("memory_type") in memory_types
                ]

            memories = canonicalize_memory_records(memories)[:search_limit]
            retention_store = get_memory_retention_store()
            if retention_store is not None:
                await retention_store.record_access(
                    user_id,
                    [
                        memory["id"]
                        for memory in memories
                        if isinstance(memory.get("id"), str)
                    ],
                )

            _record_mem0_event(
                operation="mem0.search",
                call_id=call_id,
                status="completed",
                started_at=started_at,
                result_count=len(memories),
            )
            return memories

        except Exception as e:
            _record_mem0_event(
                operation="mem0.search",
                call_id=call_id,
                status="failed",
                started_at=started_at,
                error=e,
            )
            logger.error("搜索记忆失败: %s", type(e).__name__)
            return []

    async def cleanup_stale_memories(
        self,
        *,
        user_id: str,
        dry_run: bool = True,
        max_memories: int = 500,
    ) -> dict[str, Any]:
        """Mark inactive decay-eligible memories, then delete only after grace."""

        if not self.is_enabled:
            return {
                "dry_run": dry_run,
                "total_before": 0,
                "total_after": 0,
                "counts": {action.value: 0 for action in CleanupAction},
                "applied_counts": {},
                "operations": [],
            }
        records = await self.get_all(user_id=user_id, page_size=max_memories)
        owned_records = [
            record
            for record in records[:max_memories]
            if isinstance(record, dict) and isinstance(record.get("id"), str)
        ]
        memory_ids = [record["id"] for record in owned_records]
        retention_store = get_memory_retention_store()
        cleanup_message: str | None = None
        if retention_store is None:
            decisions = fail_closed_cleanup_plan(
                owned_records,
                reason="retention state unavailable; fail closed",
            )
            cleanup_message = "Redis 清理状态不可用，本次仅保护性 KEEP，不会标记或删除记忆"
        else:
            states = await retention_store.load_states(user_id, memory_ids)
            if states is None:
                decisions = fail_closed_cleanup_plan(
                    owned_records,
                    reason="retention state read failed; fail closed",
                )
                cleanup_message = "Redis 清理状态读取失败，本次仅保护性 KEEP，不会标记或删除记忆"
            else:
                decisions = plan_cleanup(owned_records, states)
        counts = {
            action.value: sum(decision.action is action for decision in decisions)
            for action in CleanupAction
        }
        applied_counts: dict[str, int] = {}
        successful_deletes: list[str] = []
        if not dry_run and retention_store is not None and cleanup_message is None:
            cancel_ids = [
                decision.memory_id
                for decision in decisions
                if decision.action is CleanupAction.KEEP
                and decision.candidate_since is not None
                and decision.reason == "retention or inactivity threshold not reached"
            ]
            await retention_store.cancel_candidates(user_id, cancel_ids)
            mark_ids = [
                decision.memory_id
                for decision in decisions
                if decision.action is CleanupAction.MARK
            ]
            marked = await retention_store.mark_candidates(user_id, mark_ids)
            if marked:
                applied_counts[CleanupAction.MARK.value] = marked
            for decision in decisions:
                if decision.action is not CleanupAction.DELETE:
                    continue
                if await self._delete_memory_record(decision.memory_id):
                    successful_deletes.append(decision.memory_id)
            if successful_deletes:
                applied_counts[CleanupAction.DELETE.value] = len(successful_deletes)
                await retention_store.clear(user_id, successful_deletes)
        return {
            "dry_run": dry_run,
            "total_before": len(owned_records),
            "total_after": len(owned_records) - len(successful_deletes),
            "counts": counts,
            "applied_counts": applied_counts,
            "operations": [public_cleanup_decision(decision) for decision in decisions],
            "message": cleanup_message,
        }

    async def _maybe_run_retention_cleanup(self, user_id: str) -> None:
        """Run at most one two-stage cleanup sweep per active owner per day."""

        retention_store = get_memory_retention_store()
        if retention_store is None or not await retention_store.acquire_daily_sweep(user_id):
            return
        try:
            await self.cleanup_stale_memories(user_id=user_id, dry_run=False)
        except Exception as exc:
            logger.warning("长期记忆自动清理跳过: %s", type(exc).__name__)

    async def _generate_lifecycle_response(
        self,
        prompt: str,
        *,
        timeout_seconds: float | None = None,
        max_tokens: int | None = None,
    ) -> object | None:
        """Run one bounded lifecycle planning call through the request-scoped mem0 LLM."""
        llm = getattr(self._memory, "llm", None)
        generate_response = getattr(llm, "generate_response", None)
        if not callable(generate_response):
            return None
        generation_options: dict[str, Any] = {}
        generation_options["temperature"] = 0
        if max_tokens is not None:
            generation_options["max_tokens"] = max_tokens
        llm_config = getattr(llm, "config", None)
        model_name = str(getattr(llm_config, "model", "")).lower()
        base_url = str(getattr(llm_config, "openai_base_url", "")).lower()
        if model_name.startswith("deepseek") or "api.deepseek.com" in base_url:
            # DeepSeek thinking mode can consume the whole completion budget in
            # reasoning_content and leave the requested lifecycle JSON empty.
            # Lifecycle classification benefits from deterministic structured
            # output, not chain-of-thought, so disable thinking for this call.
            generation_options["extra_body"] = {"thinking": {"type": "disabled"}}
        try:
            return await _run_mem0_call(
                generate_response,
                messages=[{"role": "user", "content": prompt}],
                timeout=timeout_seconds or get_settings().mem0_add_timeout_seconds,
                **generation_options,
            )
        except Exception as exc:
            logger.warning("记忆生命周期规划降级为安全保留: %s", type(exc).__name__)
            return None

    async def _delete_memory_record(self, memory_id: str) -> bool:
        """Delete one already owner-validated record without another full owner scan."""
        try:
            await _run_mem0_call(
                self._memory.delete,
                memory_id=memory_id,
                timeout=get_settings().mem0_add_timeout_seconds,
            )
            return True
        except Exception as exc:
            logger.warning("记忆生命周期删除失败: %s", type(exc).__name__)
            return False

    async def _update_memory_record(
        self,
        memory_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Update one already owner-validated record without another full owner scan."""
        try:
            await _run_mem0_call(
                self._memory.update,
                memory_id=memory_id,
                data=content,
                metadata=metadata,
                timeout=get_settings().mem0_add_timeout_seconds,
            )
            return True
        except Exception as exc:
            logger.warning("记忆生命周期更新失败: %s", type(exc).__name__)
            return False

    async def _apply_incremental_lifecycle(
        self,
        *,
        existing: list[dict[str, Any]],
        new_records: list[dict[str, Any]],
    ) -> None:
        """Reconcile later-round candidates against owned existing memories."""
        if not new_records:
            return
        raw_plan = await self._generate_lifecycle_response(
            build_incremental_lifecycle_prompt(existing=existing, new=new_records)
        )
        operations = parse_incremental_plan(
            raw_plan,
            new_ids={record["id"] for record in new_records},
            existing_ids={record["id"] for record in existing},
        )
        existing_by_id = {record["id"]: record for record in existing}
        new_by_id = {record["id"]: record for record in new_records}
        for operation in operations:
            if operation.action is LifecycleAction.ADD:
                record = new_by_id.get(operation.new_id)
                if record and operation.retention_class:
                    metadata = dict(record.get("metadata") or {})
                    metadata.update(_retention_class_metadata(operation.retention_class))
                    admitted = await self._update_memory_record(
                        operation.new_id,
                        record["memory"],
                        metadata,
                    )
                    if admitted:
                        continue
                # Admission is opt-in. If classification or retention tagging
                # cannot be completed, remove the temporary extracted record.
                await self._delete_memory_record(operation.new_id)
                continue
            if operation.action in {LifecycleAction.DISCARD, LifecycleAction.NONE}:
                await self._delete_memory_record(operation.new_id)
                continue
            if operation.action is LifecycleAction.UPDATE:
                target = existing_by_id.get(operation.target_id or "")
                metadata = dict(target.get("metadata") or {}) if target else {}
                if operation.retention_class:
                    metadata.update(_retention_class_metadata(operation.retention_class))
                if operation.target_id and operation.content:
                    await self._update_memory_record(
                        operation.target_id,
                        operation.content,
                        metadata or None,
                    )
                # The extracted candidate is only a staging record. The source
                # interview remains available even if the canonical update fails.
                await self._delete_memory_record(operation.new_id)
                continue
            if operation.action is LifecycleAction.DELETE and operation.target_id:
                await self._delete_memory_record(operation.target_id)
                await self._delete_memory_record(operation.new_id)

    async def consolidate_existing_memories(
        self,
        *,
        user_id: str,
        dry_run: bool = True,
        max_memories: int = 200,
    ) -> dict[str, Any]:
        """Preview or apply an owner-scoped, LLM-validated historical consolidation plan."""
        if not self.is_enabled:
            return {
                "dry_run": dry_run,
                "total_before": 0,
                "total_after": 0,
                "counts": {"KEEP": 0, "UPDATE": 0, "DELETE": 0},
                "applied_counts": {},
                "operations": [],
            }

        records = await self.get_all(user_id=user_id, page_size=max_memories)
        owned_records = [
            record
            for record in records[:max_memories]
            if isinstance(record, dict)
            and isinstance(record.get("id"), str)
            and isinstance(record.get("memory"), str)
        ]
        raw_plan = await self._generate_lifecycle_response(
            build_historical_consolidation_prompt(records=owned_records),
            timeout_seconds=max(get_settings().mem0_add_timeout_seconds, 180.0),
            # Historical batches need substantially more output room than one
            # incremental turn.  Some OpenAI-compatible reasoning models emit
            # hidden reasoning before the requested JSON; the request-scoped
            # mem0 default of 2k tokens can therefore finish with empty content.
            max_tokens=max(get_settings().llm_max_tokens, 8000),
        )
        operations = parse_historical_plan(
            raw_plan,
            owned_ids={record["id"] for record in owned_records},
        )
        raw_counts = lifecycle_counts(operations)
        counts = {
            action.value: raw_counts.get(action.value, 0)
            for action in ConsolidationAction
        }
        applied_counts: dict[str, int] = {}
        successful_deletes = 0

        if not dry_run:
            failed_canonical_updates: set[str] = set()
            update_operations = [
                operation
                for operation in operations
                if operation.action is ConsolidationAction.UPDATE
            ]
            delete_operations = [
                operation
                for operation in operations
                if operation.action is ConsolidationAction.DELETE
            ]
            for operation in update_operations:
                applied = False
                if operation.content:
                    applied = await self._update_memory_record(
                        operation.memory_id,
                        operation.content,
                    )
                if applied:
                    key = operation.action.value
                    applied_counts[key] = applied_counts.get(key, 0) + 1
                else:
                    failed_canonical_updates.add(operation.memory_id)
            for operation in delete_operations:
                if operation.canonical_id in failed_canonical_updates:
                    continue
                applied = await self._delete_memory_record(operation.memory_id)
                successful_deletes += int(applied)
                if applied:
                    key = operation.action.value
                    applied_counts[key] = applied_counts.get(key, 0) + 1

        projected_deletes = counts[ConsolidationAction.DELETE.value]
        return {
            "dry_run": dry_run,
            "total_before": len(owned_records),
            "total_after": len(owned_records)
            - (projected_deletes if dry_run else successful_deletes),
            "counts": counts,
            "applied_counts": applied_counts,
            "operations": [public_operation(operation) for operation in operations],
        }

    async def add_interaction(
        self,
        *,
        user_id: str,
        session_id: str,
        user_message: str,
        assistant_message: str,
        metadata: Optional[dict] = None,
    ) -> Optional[dict]:
        """
        添加对话交互记忆

        Args:
            user_id: 用户 ID
            session_id: 会话 ID
            user_message: 用户消息
            assistant_message: 助手回复
            metadata: 额外元数据

        Returns:
            dict: mem0 返回的结果，失败返回 None
        """
        if not self.is_enabled:
            return None

        started_at = perf_counter()
        call_id = new_runtime_event_id("mem0_interaction")
        _record_mem0_event(
            operation="mem0.add_interaction", call_id=call_id, status="started", started_at=started_at
        )
        try:
            existing = await self.search_memories(
                user_id=user_id,
                query=user_message,
                limit=10,
            )
            # 构造消息格式
            messages = [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": assistant_message},
            ]

            # 构造 metadata
            meta = {
                "project": "agent_interview",
                "source": "chat_turn",
                "session_id": session_id,
                "origin_agent_id": "interview-agent",
                **_retention_metadata(),
            }
            if metadata:
                meta.update(metadata)

            # mem0 的 add 是同步的
            result = await _run_mem0_call(
                self._memory.add,
                messages=messages,
                user_id=user_id,
                metadata=meta,
                prompt=INTERVIEW_MEMORY_EXTRACTION_INSTRUCTIONS,
                timeout=get_settings().mem0_add_timeout_seconds,
            )
            await self._apply_incremental_lifecycle(
                existing=existing,
                new_records=extract_result_records(result),
            )
            await self._maybe_run_retention_cleanup(user_id)

            logger.debug(f"添加交互记忆成功: user_id={user_id}")
            _record_mem0_event(
                operation="mem0.add_interaction", call_id=call_id, status="completed",
                started_at=started_at, item_count=2,
            )
            return result

        except Exception as e:
            _record_mem0_event(
                operation="mem0.add_interaction", call_id=call_id, status="failed",
                started_at=started_at, item_count=2, error=e,
            )
            logger.error("添加交互记忆失败: %s", type(e).__name__)
            return None

    async def add_summary_memory(
        self,
        *,
        user_id: str,
        session_id: str,
        content: str,
        memory_type: str,
        metadata: Optional[dict] = None,
    ) -> Optional[dict]:
        """Do not duplicate assistant-generated report artifacts into long-term memory."""
        _ = (user_id, session_id, content, memory_type, metadata)
        logger.info("跳过面试报告到长期记忆的自动沉淀")
        return None

    async def add_memory(
        self,
        *,
        user_id: str,
        content: str,
        memory_type: str | None = None,
        metadata: Optional[dict] = None,
    ) -> Optional[dict]:
        """Store one user-authored memory without asking mem0 to infer or rewrite it."""
        if not self.is_enabled:
            return None

        started_at = perf_counter()
        call_id = new_runtime_event_id("mem0_manual_add")
        _record_mem0_event(
            operation="mem0.add_manual", call_id=call_id, status="started", started_at=started_at
        )
        try:
            normalized_content = normalize_memory_text(content)
            if normalized_content:
                existing_memories = await self.get_all(user_id=user_id, page_size=1000)
                for existing in existing_memories:
                    existing_content = str(existing.get("memory", ""))
                    existing_id = existing.get("id")
                    if (
                        isinstance(existing_id, str)
                        and normalize_memory_text(existing_content) == normalized_content
                    ):
                        return {
                            "results": [
                                {
                                    "id": existing_id,
                                    "memory": existing_content,
                                    "event": "NONE",
                                }
                            ]
                        }

            meta = {
                "project": "agent_interview",
                "source": "manual",
                **_retention_metadata(),
                **_retention_class_metadata(MemoryRetentionClass.CORE),
            }
            if memory_type:
                meta["memory_type"] = memory_type
            if metadata:
                meta.update(metadata)

            result = await _run_mem0_call(
                self._memory.add,
                content,
                user_id=user_id,
                agent_id="interview-agent",
                run_id="manual-memory",
                metadata=meta,
                infer=False,
                timeout=get_settings().mem0_add_timeout_seconds,
            )
            _record_mem0_event(
                operation="mem0.add_manual", call_id=call_id, status="completed",
                started_at=started_at, item_count=1,
            )
            return result
        except Exception as exc:
            _record_mem0_event(
                operation="mem0.add_manual", call_id=call_id, status="failed",
                started_at=started_at, item_count=1, error=exc,
            )
            logger.error("手动添加记忆失败: %s", type(exc).__name__)
            return None

    async def get_all(
        self,
        *,
        user_id: str,
        page_size: int = 100,
    ) -> list[dict]:
        """
        获取用户全部记忆

        Args:
            user_id: 用户 ID
            page_size: 每页数量

        Returns:
            list[dict]: 记忆列表
        """
        if not self.is_enabled:
            return []

        try:
            # mem0 v2+ 的 get_all 只接受 filters={"user_id": ...} + top_k；
            # 顶层 user_id/page_size 参数会被上游拒绝并抛 ValueError。
            result = await asyncio.to_thread(
                self._memory.get_all,
                filters={"user_id": user_id},
                top_k=page_size,
            )

            # 处理返回格式
            if isinstance(result, dict):
                return result.get("results", [])
            elif isinstance(result, list):
                return result
            return []

        except Exception as e:
            logger.error("获取全部记忆失败: %s", type(e).__name__)
            return []

    async def history(
        self,
        *,
        user_id: str,
        memory_id: str,
    ) -> list[dict]:
        """获取一条属于当前用户的记忆变更历史。"""
        if not self.is_enabled:
            return []

        try:
            all_memories = await self.get_all(user_id=user_id)
            memory_ids = [memory.get("id") for memory in all_memories]
            if memory_id not in memory_ids:
                logger.warning("记忆 %s 不属于用户 %s", memory_id, user_id)
                return []

            result = await asyncio.to_thread(self._memory.history, memory_id=memory_id)
            return result if isinstance(result, list) else []
        except Exception as exc:
            logger.error("获取记忆历史失败: %s", type(exc).__name__)
            return []

    async def update_memory(
        self,
        *,
        user_id: str,
        memory_id: str,
        content: str,
    ) -> Optional[dict]:
        """Update one memory after verifying that it belongs to the current user."""
        if not self.is_enabled:
            return None

        try:
            memories = await self.get_all(user_id=user_id)
            target = next((item for item in memories if item.get("id") == memory_id), None)
            if target is None:
                logger.warning("记忆 %s 不属于用户 %s", memory_id, user_id)
                return None
            metadata = dict(target.get("metadata") or {})
            raw_retention_class = str(metadata.get("retention_class") or "").lower()
            try:
                retention_class = MemoryRetentionClass(raw_retention_class)
            except ValueError:
                # A user-authored edit explicitly reconfirms a legacy record.
                # Manual and legacy memories fail closed into the protected tier.
                retention_class = MemoryRetentionClass.CORE
            metadata.update(_retention_class_metadata(retention_class))
            result = await _run_mem0_call(
                self._memory.update,
                memory_id=memory_id,
                data=content,
                metadata=metadata,
                timeout=get_settings().mem0_add_timeout_seconds,
            )
            retention_store = get_memory_retention_store()
            if retention_store is not None:
                await retention_store.record_access(user_id, [memory_id])
            return result
        except Exception as exc:
            logger.error("更新记忆失败: %s", type(exc).__name__)
            return None

    async def delete(
        self,
        *,
        user_id: str,
        memory_id: str,
    ) -> bool:
        """
        删除记忆

        Args:
            user_id: 用户 ID（用于校验归属）
            memory_id: 记忆 ID

        Returns:
            bool: 是否删除成功
        """
        if not self.is_enabled:
            return False

        try:
            # 先校验记忆归属
            all_memories = await self.get_all(user_id=user_id)
            memory_ids = [m.get("id") for m in all_memories]

            if memory_id not in memory_ids:
                logger.warning(f"记忆 {memory_id} 不属于用户 {user_id}")
                return False

            await asyncio.to_thread(
                self._memory.delete,
                memory_id=memory_id,
            )
            retention_store = get_memory_retention_store()
            if retention_store is not None:
                await retention_store.clear(user_id, [memory_id])

            logger.info(f"删除记忆成功: memory_id={memory_id}, delete_sync_policy=mem0_delete_by_user_or_expiry")
            return True

        except Exception as e:
            logger.error("删除记忆失败: %s", type(e).__name__)
            return False

    async def delete_all(
        self,
        *,
        user_id: str,
        confirm: bool = False,
    ) -> bool:
        """
        清空用户全部记忆

        Args:
            user_id: 用户 ID
            confirm: 必须为 True 才执行删除

        Returns:
            bool: 是否删除成功
        """
        if not confirm:
            logger.warning("delete_all 需要 confirm=True")
            return False

        if not self.is_enabled:
            return False

        try:
            owned_memories = await self.get_all(user_id=user_id, page_size=1000)
            owned_memory_ids = [
                memory_id
                for item in owned_memories
                if isinstance((memory_id := item.get("id")), str)
            ]
            await asyncio.to_thread(
                self._memory.delete_all,
                user_id=user_id,
            )
            retention_store = get_memory_retention_store()
            if retention_store is not None:
                await retention_store.clear(user_id, owned_memory_ids)

            logger.info(f"清空用户记忆成功: user_id={user_id}, delete_sync_policy=mem0_delete_all_by_user")
            return True

        except Exception as e:
            logger.error("清空用户记忆失败: %s", type(e).__name__)
            return False


async def get_agent_memory_service(api_config: Optional[dict[str, Any]] = None) -> AgentMemoryService:
    """
    获取 AgentMemoryService。

    无 api_config 时返回服务端 .env 单例；有前端配置时按配置缓存实例，
    支持不同用户/浏览器使用不同的 mem0 LLM 和 Embedding Key。
    """
    global _agent_memory_service

    config = get_mem0_config(api_config)
    if api_config is None:
        if _agent_memory_service is not None and _agent_memory_service.is_enabled:
            return _agent_memory_service
        candidate = AgentMemoryService(config)
        await candidate.initialize()
        # Failed initialization must not poison the process singleton forever.
        # A later request may arrive after PostgreSQL or model configuration recovers.
        if candidate.is_enabled:
            _agent_memory_service = candidate
        else:
            _agent_memory_service = None
        return candidate

    cache_key = _memory_config_cache_key(config)
    service = _agent_memory_services.get(cache_key)
    if service is None or not service.is_enabled:
        candidate = AgentMemoryService(config)
        await candidate.initialize()
        service = candidate
    if service.is_enabled:
        _agent_memory_services[cache_key] = service
    else:
        _agent_memory_services.pop(cache_key, None)
    return service


def get_agent_memory_runtime_status() -> dict[str, Any]:
    """Return a credential-free snapshot of mem0 readiness in this process."""
    server_ready = bool(_agent_memory_service and _agent_memory_service.is_enabled)
    return {
        "mode": "server" if server_ready else "request_scoped",
        "server_ready": server_ready,
        "request_scoped_ready": sum(
            1 for service in _agent_memory_services.values() if service.is_enabled
        ),
    }


async def close_agent_memory_service() -> None:
    """Clear all process-local mem0 clients without exposing request credentials."""
    global _agent_memory_service
    _agent_memory_service = None
    _agent_memory_services.clear()
    logger.info("✓ AgentMemoryService 已关闭")
