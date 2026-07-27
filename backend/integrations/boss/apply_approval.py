"""投递预览许可：把一次人工确认绑定到具体用户、岗位和发送内容。"""

import asyncio
import hashlib
import json
import os
import secrets
import time
from dataclasses import asdict, dataclass
from typing import Optional, Protocol

from .security import is_allowed_apply_url


class ApprovalError(ValueError):
    """预览许可无效、过期、内容不匹配或已使用。"""


def _digest(value: str) -> str:
    """为审批内容生成不可逆摘要，用于校验确认令牌与原始请求的一致性。

    Args:
        value: 取值。
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PendingApproval:
    """一次性 BOSS 投递审批许可，绑定 user、岗位、来源和发送内容摘要及过期时间；消费时必须原子删除，禁止重放或跨 owner 使用。"""
    user_id: str
    job_id: int
    greeting_digest: str
    source_url_digest: str
    resume_id: Optional[int]
    expires_at: float


class ApprovalStore(Protocol):
    """一次性审批许可的存储协议；实现可使用内存或 Redis，但必须提供 TTL、owner 隔离和消费即删除语义。"""

    async def put(self, token: str, item: PendingApproval, ttl_seconds: int) -> None:
        """写入带 TTL 的待处理记录，并以命名空间隔离用户和业务对象。

        Args:
            token: 访问令牌。
            item: 单条数据。
            ttl_seconds: 短期审批或缓存状态的生命周期限制，用于控制重放窗口和资源占用。
        """
        ...

    async def pop(self, token: str) -> PendingApproval | None:
        """读取并删除待处理记录，使审批或缓存消费具备一次性语义。

        Args:
            token: 访问令牌。
        """
        ...


class MemoryApprovalStore:
    """本地开发降级存储；重启后许可安全失效。"""

    def __init__(self, max_pending: int = 1000) -> None:
        """初始化 `MemoryApprovalStore` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端仅在后续方法调用时承担对应的访问边界。

        Args:
            max_pending: 短期审批或缓存状态的生命周期限制，用于控制重放窗口和资源占用。
        """
        self._max_pending = max_pending
        self._items: dict[str, PendingApproval] = {}
        self._lock = asyncio.Lock()

    async def put(self, token: str, item: PendingApproval, ttl_seconds: int) -> None:
        """写入带 TTL 的待处理记录，并以命名空间隔离用户和业务对象。

        Args:
            token: 访问令牌。
            item: 单条数据。
            ttl_seconds: 短期审批或缓存状态的生命周期限制，用于控制重放窗口和资源占用。
        """
        async with self._lock:
            superseded = [
                key
                for key, current in self._items.items()
                if current.user_id == item.user_id and current.job_id == item.job_id
            ]
            for key in superseded:
                self._items.pop(key, None)
            if len(self._items) >= self._max_pending:
                oldest = min(self._items, key=lambda key: self._items[key].expires_at)
                self._items.pop(oldest, None)
            self._items[token] = item

    async def pop(self, token: str) -> PendingApproval | None:
        """读取并删除待处理记录，使审批或缓存消费具备一次性语义。

        Args:
            token: 访问令牌。
        """
        async with self._lock:
            return self._items.pop(token, None)


class RedisApprovalStore:
    """跨 worker 的短期审批存储；读取即原子删除，避免重放。"""

    _PUT_SCRIPT = """
    local previous = redis.call('GET', KEYS[2])
    if previous then redis.call('DEL', ARGV[4] .. previous) end
    redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3])
    redis.call('SET', KEYS[2], ARGV[1], 'EX', ARGV[3])
    return true
    """
    _POP_SCRIPT = """
    local payload = redis.call('GET', KEYS[1])
    if not payload then return false end
    redis.call('DEL', KEYS[1])
    if redis.call('GET', KEYS[2]) == ARGV[1] then redis.call('DEL', KEYS[2]) end
    return payload
    """

    def __init__(self, redis_url: str) -> None:
        """初始化 `RedisApprovalStore` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端仅在后续方法调用时承担对应的访问边界。

        Args:
            redis_url: redis URL。
        """
        from redis.asyncio import Redis

        self._client = Redis.from_url(redis_url, decode_responses=True)

    @staticmethod
    def _token_key(token: str) -> tuple[str, str]:
        """生成审批令牌的存储 key，使用哈希或命名空间隔离避免泄露令牌原文。

        Args:
            token: 访问令牌。
        """
        token_hash = _digest(token)
        return f"agent-interview:approval:{token_hash}", token_hash

    @staticmethod
    def _latest_key(item: PendingApproval) -> str:
        """根据审批项生成最新记录 key，保证同一用户和岗位的确认状态可幂等读取。

        Args:
            item: 单条数据。
        """
        owner = _digest(f"{item.user_id}\0{item.job_id}")
        return f"agent-interview:approval-latest:{owner}"

    async def put(self, token: str, item: PendingApproval, ttl_seconds: int) -> None:
        """写入带 TTL 的待处理记录，并以命名空间隔离用户和业务对象。

        Args:
            token: 访问令牌。
            item: 单条数据。
            ttl_seconds: 短期审批或缓存状态的生命周期限制，用于控制重放窗口和资源占用。
        """
        item_key, token_hash = self._token_key(token)
        latest_key = self._latest_key(item)
        await self._client.eval(
            self._PUT_SCRIPT,
            2,
            item_key,
            latest_key,
            token_hash,
            json.dumps(asdict(item), separators=(",", ":")),
            ttl_seconds,
            "agent-interview:approval:",
        )

    async def pop(self, token: str) -> PendingApproval | None:
        """读取并删除待处理记录，使审批或缓存消费具备一次性语义。

        Args:
            token: 访问令牌。
        """
        item_key, token_hash = self._token_key(token)
        raw = await self._client.get(item_key)
        if not raw:
            return None
        item = PendingApproval(**json.loads(raw))
        consumed = await self._client.eval(
            self._POP_SCRIPT,
            2,
            item_key,
            self._latest_key(item),
            token_hash,
        )
        return PendingApproval(**json.loads(consumed)) if consumed else None


class ApplyApprovalRegistry:
    """短期、一次性的预览许可；存储后端可替换。"""

    def __init__(
        self,
        ttl_seconds: int = 300,
        max_pending: int = 1000,
        store: ApprovalStore | None = None,
    ) -> None:
        """初始化 `ApplyApprovalRegistry` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端仅在后续方法调用时承担对应的访问边界。

        Args:
            ttl_seconds: 短期审批或缓存状态的生命周期限制，用于控制重放窗口和资源占用。
            max_pending: 短期审批或缓存状态的生命周期限制，用于控制重放窗口和资源占用。
            store: 经过类型边界校验的 `store`；其格式和可选值由参数类型及调用流程约束。
        """
        self._ttl_seconds = ttl_seconds
        self._store = store or MemoryApprovalStore(max_pending=max_pending)

    async def issue(
        self,
        *,
        user_id: str,
        job_id: int,
        greeting_text: str,
        source_url: str,
        resume_id: Optional[int],
    ) -> tuple[str, int]:
        """签发带有效期和内容摘要的人工审批令牌，令牌仅绑定指定用户和岗位。

        Args:
            user_id: 当前用户标识。
            job_id: 岗位标识。
            greeting_text: greeting 文本内容。
            source_url: source URL。
            resume_id: 简历标识。
        """
        token = secrets.token_urlsafe(32)
        item = PendingApproval(
            user_id=user_id,
            job_id=job_id,
            greeting_digest=_digest(greeting_text),
            source_url_digest=_digest(source_url),
            resume_id=resume_id,
            expires_at=time.time() + self._ttl_seconds,
        )
        await self._store.put(token, item, self._ttl_seconds)
        return token, self._ttl_seconds

    async def consume(
        self,
        token: str,
        *,
        user_id: str,
        job_id: int,
        greeting_text: str,
        source_url: str,
        resume_id: Optional[int],
    ) -> None:
        """原子消费人工审批令牌，校验 owner、岗位、内容摘要和有效期后才允许继续投递。

        Args:
            token: 访问令牌。
            user_id: 当前用户标识。
            job_id: 岗位标识。
            greeting_text: greeting 文本内容。
            source_url: source URL。
            resume_id: 简历标识。
        """
        item = await self._store.pop(token)
        if item is None:
            raise ApprovalError("预览许可无效或已使用，请重新预览")
        if item.expires_at <= time.time():
            raise ApprovalError("预览许可已过期，请重新预览")

        actual = (
            user_id,
            job_id,
            _digest(greeting_text),
            _digest(source_url),
            resume_id,
        )
        expected = (
            item.user_id,
            item.job_id,
            item.greeting_digest,
            item.source_url_digest,
            item.resume_id,
        )
        if actual != expected:
            raise ApprovalError("投递内容与预览不一致，请重新预览")


def _approval_ttl_seconds() -> int:
    """读取人工审批令牌的有效期，令牌过期后不得继续执行投递动作。"""
    try:
        value = int(os.getenv("BOSS_APPLY_APPROVAL_TTL_SECONDS", "300"))
    except ValueError:
        value = 300
    return min(max(value, 30), 1800)


def _approval_store() -> ApprovalStore:
    """返回当前配置的审批存储实现，优先使用共享存储并保留本地降级边界。"""
    redis_url = os.getenv("REDIS_URL")
    return RedisApprovalStore(redis_url) if redis_url else MemoryApprovalStore()


apply_approval_registry = ApplyApprovalRegistry(
    ttl_seconds=_approval_ttl_seconds(),
    store=_approval_store(),
)
