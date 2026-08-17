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
from app.domain.memory import canonicalize_memory_records, is_writable_memory_source, normalize_memory_text
from observability import record_external_io_event
from observability.runtime_events import (
    ExternalIOObservationEvent,
    new_runtime_event_id,
)

from .config import (
    get_mem0_config,
    get_mem0_database_mode,
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
长期记忆是紧凑、可复用的候选人画像，不是对话摘要。只提取用户明确表达、跨未来面试仍有价值的稳定信息；不确定时不生成，每轮最多两个候选记忆。

语言规则：普通叙述必须使用中文；仅技术栈、产品名、协议名、组织名等必要专有名词可以保留英文原文。不得用完整英文句子描述用户事实。

允许的类别：
- 身份、教育背景或稳定工作经历；
- 每个有名称的项目或工作经历保留一条规范摘要；
- 稳定技术栈或已验证能力；
- 明确的职业方向、长期偏好、约束或目标；
- 仅当用户明确说明其反复出现时，才记录短板。

禁止提取助手生成的事实、评分、优势、反馈、辅导建议、回答模板、临时面试表现、通用经验、假设示例、寒暄确认，或本应合并进既有项目摘要的组件级细节。不得从一次回答推断人格或长期短板。用户补充既有项目、技术栈或目标时，应生成适合合并到该规范主题的候选记忆，而不是独立碎片。
""".strip()

# mem0 上游默认启用匿名 PostHog 遥测；除非运维人员在导入本模块前明确选择启用，
# 否则本产品的记忆运行时保持私有和离线。
os.environ.setdefault("MEM0_TELEMETRY", "False")

# 全局单例
_agent_memory_service: Optional["AgentMemoryService"] = None
_agent_memory_services: dict[str, "AgentMemoryService"] = {}
_last_memory_readiness_category: str | None = None


def classify_memory_initialization_error(exc: BaseException) -> str:
    """将依赖故障映射为稳定且不含凭据的就绪状态类别。

    Args:
        exc: 异常实例。
    """
    text = f"{type(exc).__name__} {exc}".casefold()
    if any(token in text for token in (
        "password authentication failed",
        "invalidpassword",
        "authenticationerror",
        "authentication failed",
    )):
        return "database_authentication_failed"
    if any(token in text for token in (
        "type vector does not exist",
        "undefinedobject",
        "vector dimension",
        "embedding_model_dims",
    )):
        return "vector_schema_error"
    if any(token in text for token in (
        "connection refused",
        "connection timed out",
        "could not connect",
        "operationalerror",
    )):
        return "database_unavailable"
    return "initialization_failed"


async def _run_mem0_call(
    function: Any,
    *args: Any,
    timeout: float,
    **kwargs: Any,
) -> Any:
    """在独立外部 IO 超时约束下运行一次同步 mem0 操作。

    Args:
        function: 回调函数。
        timeout: 超时时间（秒）。
        args: 位置参数。
        kwargs: 关键字参数。
    """
    return await asyncio.wait_for(
        asyncio.to_thread(function, *args, **kwargs),
        timeout=timeout,
    )


def _external_error_category(exc: BaseException) -> str:
    """区分外部依赖超时与其他降级 IO 故障。

    Args:
        exc: 异常实例。
    """
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
    """记录 mem0 的安全外部 IO 摘要，不上传记忆正文、用户 ID 或过滤器。

    Args:
        operation: 操作标识。
        call_id: 调用 ID。
        status: 状态字符串。
        started_at: 开始时间。
        item_count: item 的数量。
        result_count: result 的数量。
        error: 异常实例。
    """

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
    """为 mem0 配置生成不泄露明文 key 的缓存键。

    Args:
        config: 配置字典。
    """
    if config is None:
        return "disabled"

    def scrub(value: Any) -> Any:
        """递归移除记忆配置中的密钥类字段，只用于生成缓存指纹，不得用于实际 mem0 连接。

        Args:
            value: 值。
        """
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
    """构建渐进清理策略使用的不含正文元数据。

    Args:
        retention_class: 传入的 retention_class 值。
    """

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
        self._readiness_category = "not_initialized" if config is not None else "model_channels_missing"

    async def initialize(self) -> bool:
        """初始化 mem0 客户端，并返回其是否已可处理请求。"""
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
            self._readiness_category = "ready"
            logger.info("✓ AgentMemoryService 初始化成功")
            return True
        except Exception as exc:
            logger.error("✗ AgentMemoryService 初始化失败: %s", type(exc).__name__)
            self._enabled = False
            self._memory = None
            self._initialization_error = type(exc).__name__
            self._readiness_category = classify_memory_initialization_error(exc)
            return False

    @property
    # property将一个方法转换成属性，让你可以像访问属性一样调用方法
    def is_enabled(self) -> bool:
        """检查服务是否启用"""
        return self._enabled and self._memory is not None

    @property
    def initialization_error(self) -> str | None:
        """仅返回最近一次初始化尝试的安全异常类型。"""
        return self._initialization_error

    @property
    def readiness_category(self) -> str:
        """返回一个稳定且已脱敏的就绪状态类别，用于 API 诊断。"""
        return self._readiness_category

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
            try:
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
            except Exception as exc:
                # 访问遥测是尽力而为；Redis 或就绪状态漂移不应
                # 抹掉一次原本成功的用户范围 mem0 查询。
                logger.warning("记忆访问状态记录失败: %s", type(exc).__name__)

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
        """先标记可衰减的非活跃记忆，仅在宽限期后删除。

        Args:
            user_id: 用户 ID，所有者范围限定。
            dry_run: 是否仅预演。
            max_memories: memories 的最大值。
        """

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
        """每个活跃用户每天最多运行一次两阶段清理扫描。

        Args:
            user_id: 用户 ID，所有者范围限定。
        """

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
        """通过请求范围内的 mem0 LLM 运行一次有边界的生命周期规划调用。

        Args:
            prompt: 提示词文本。
            timeout_seconds: 超时秒数。
            max_tokens: tokens 的最大值。
        """
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
            # DeepSeek 思考模式可能把全部生成预算消耗在 reasoning_content 中，
            # 导致请求的生命周期 JSON 为空。生命周期分类更依赖确定性的结构化输出，
            # 而不是思维链，因此本次调用关闭思考模式。
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
        """删除一条已完成用户归属校验的记录，不再执行完整归属扫描。

        Args:
            memory_id: memory 的 ID。
        """
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
        """更新一条已完成用户归属校验的记录，不再执行完整归属扫描。

        Args:
            memory_id: memory 的 ID。
            content: 文本内容。
            metadata: 元数据字典。
        """
        try:
            result = await _run_mem0_call(
                self._memory.update,
                memory_id=memory_id,
                data=content,
                metadata=metadata,
                timeout=get_settings().mem0_add_timeout_seconds,
            )
            return result is not None and result is not False
        except Exception as exc:
            logger.warning("记忆生命周期更新失败: %s", type(exc).__name__)
            return False

    async def _apply_incremental_lifecycle(
        self,
        *,
        existing: list[dict[str, Any]],
        new_records: list[dict[str, Any]],
    ) -> None:
        """将后续轮次候选记忆与当前用户既有记忆进行对账。

        Args:
            existing: 已有记录。
            new_records: 传入的 new_records 值。
        """
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
                if record and operation.retention_class and operation.content:
                    metadata = dict(record.get("metadata") or {})
                    metadata.update(_retention_class_metadata(operation.retention_class))
                    admitted = await self._update_memory_record(
                        operation.new_id,
                        operation.content,
                        metadata,
                    )
                    if admitted:
                        continue
                # 写入长期记忆必须显式接纳；如果分类或保留等级标注无法完成，
                # 就移除临时抽取出的记录。
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
                # 抽取出的候选项只是暂存记录；即使规范记录更新失败，
                # 原始面试内容仍然可用。
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
        """预览或应用限定在当前用户范围内、经 LLM 校验的历史合并计划。

        Args:
            user_id: 用户 ID，所有者范围限定。
            dry_run: 是否仅预演。
            max_memories: memories 的最大值。
        """
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
            # 历史批次比单次增量轮次需要更多输出空间。部分兼容 OpenAI 的推理模型
            # 会在请求的 JSON 之前生成隐藏推理内容；因此，请求范围 mem0 默认的
            # 2k token 可能最终产出空内容。
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
        """Persist a completed report's weakness summary with explicit provenance.

        Args:
            user_id: 用户 ID，所有者范围限定。
            session_id: 面试会话 ID。
            content: 文本内容。
            memory_type: 记忆类型。
            metadata: 元数据字典。
        """
        if not self.is_enabled or memory_type != "weakness":
            return None

        started_at = perf_counter()
        call_id = new_runtime_event_id("mem0_report_weakness")
        _record_mem0_event(
            operation="mem0.add_report_weakness",
            call_id=call_id,
            status="started",
            started_at=started_at,
        )
        try:
            meta = {
                "project": "agent_interview",
                "source": "interview_report",
                "session_id": session_id,
                "origin_agent_id": "interview-agent",
                "memory_type": "weakness",
                "memory_source": "interview_weakness",
                **_retention_metadata(),
                **_retention_class_metadata(MemoryRetentionClass.TRANSIENT),
            }
            if metadata:
                meta.update(metadata)
            meta.update({
                "source": "interview_report",
                "session_id": session_id,
                "memory_type": "weakness",
                "memory_source": "interview_weakness",
            })
            result = await _run_mem0_call(
                self._memory.add,
                content,
                user_id=user_id,
                agent_id="interview-agent",
                run_id="interview-report-memory",
                metadata=meta,
                infer=False,
                timeout=get_settings().mem0_add_timeout_seconds,
            )
            _record_mem0_event(
                operation="mem0.add_report_weakness",
                call_id=call_id,
                status="completed",
                started_at=started_at,
                item_count=1,
            )
            return result
        except Exception as exc:
            _record_mem0_event(
                operation="mem0.add_report_weakness",
                call_id=call_id,
                status="failed",
                started_at=started_at,
                item_count=1,
                error=exc,
            )
            logger.error("面试短板记忆写入失败: %s", type(exc).__name__)
            return None

    async def add_memory(
        self,
        *,
        user_id: str,
        content: str,
        memory_type: str | None = None,
        memory_source: str | None = None,
        metadata: Optional[dict] = None,
    ) -> Optional[dict]:
        """Store a user-authored memory without mem0 inference or rewriting.

        Args:
            user_id: 用户 ID，所有者范围限定。
            content: 文本内容。
            memory_type: 记忆类型。
            memory_source: 传入的 memory_source 值。
            metadata: 元数据字典。
        """
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
            if is_writable_memory_source(memory_source):
                meta["memory_source"] = memory_source
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
        """获取一条属于当前用户的记忆变更历史。

        Args:
            user_id: 用户 ID，所有者范围限定。
            memory_id: memory 的 ID。
        """
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
        """在确认记忆属于当前用户后更新一条记忆。

        Args:
            user_id: 用户 ID，所有者范围限定。
            memory_id: memory 的 ID。
            content: 文本内容。
        """
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
                # 用户手工编辑会显式重新确认旧记录。
                # 手工记忆和旧记忆按保守策略归入受保护等级。
                retention_class = MemoryRetentionClass.CORE
            metadata.update(_retention_class_metadata(retention_class))
            result = await _run_mem0_call(
                self._memory.update,
                memory_id=memory_id,
                data=content,
                metadata=metadata,
                timeout=get_settings().mem0_add_timeout_seconds,
            )
            try:
                retention_store = get_memory_retention_store()
                if retention_store is not None:
                    await retention_store.record_access(user_id, [memory_id])
            except Exception as exc:
                # 访问遥测是尽力而为；Redis 就绪状态漂移不应抹掉一次已经成功的 mem0 更新。
                logger.warning("记忆访问状态记录失败: %s", type(exc).__name__)
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

    Args:
        api_config: 前端请求携带的模型通道配置。
    """
    global _agent_memory_service, _last_memory_readiness_category

    config = get_mem0_config(api_config)
    if api_config is None:
        if _agent_memory_service is not None and _agent_memory_service.is_enabled:
            return _agent_memory_service
        candidate = AgentMemoryService(config)
        await candidate.initialize()
        # 初始化失败不应永久污染进程单例。
        # 后续请求可能在 PostgreSQL 或模型配置恢复后到达。
        _last_memory_readiness_category = candidate.readiness_category
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
    _last_memory_readiness_category = service.readiness_category
    if service.is_enabled:
        _agent_memory_services[cache_key] = service
    else:
        _agent_memory_services.pop(cache_key, None)
    return service


def get_agent_memory_runtime_status() -> dict[str, Any]:
    """返回当前进程中 mem0 就绪状态的无凭据快照。"""
    server_ready = bool(_agent_memory_service and _agent_memory_service.is_enabled)
    request_scoped_ready = sum(
        1 for service in _agent_memory_services.values() if service.is_enabled
    )
    if server_ready:
        readiness_category = "ready"
    elif request_scoped_ready:
        readiness_category = "request_scoped_ready"
    elif _last_memory_readiness_category:
        readiness_category = _last_memory_readiness_category
    else:
        try:
            readiness_category = (
                "model_channels_missing"
                if get_mem0_config() is None
                else "not_initialized"
            )
        except Exception:
            readiness_category = "initialization_failed"
    return {
        "mode": "server" if server_ready else "request_scoped",
        "server_ready": server_ready,
        "request_scoped_ready": request_scoped_ready,
        "readiness_category": readiness_category,
        "database_mode": get_mem0_database_mode(),
    }


async def close_agent_memory_service() -> None:
    """清理所有进程本地 mem0 客户端，不暴露请求凭据。"""
    global _agent_memory_service, _last_memory_readiness_category
    _agent_memory_service = None
    _last_memory_readiness_category = None
    _agent_memory_services.clear()
    logger.info("✓ AgentMemoryService 已关闭")
