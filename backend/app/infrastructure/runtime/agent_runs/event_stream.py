"""AgentRun 事件流重放契约。"""

from datetime import datetime


def replay_cursor(*, after_sequence: int = 0, last_event_id: str | None = None) -> int:
    """计算事件重放游标。

    SSE 断线重连时浏览器会通过 ``Last-Event-ID`` 带回最后收到的事件 ID；
    查询参数 ``after_sequence`` 可用于普通 HTTP 调用指定游标。两者同时存在时取较大值。
    非数字 ``Last-Event-ID`` 视为无效，避免客户端异常输入导致 500。
    """
    normalized_after = max(0, int(after_sequence or 0))
    if last_event_id is None:
        return normalized_after
    value = str(last_event_id).strip()
    if not value.isdigit():
        return normalized_after
    return max(normalized_after, int(value))


def build_run_event_envelope(
    *,
    run_id: str,
    event_type: str,
    stage: str | None = None,
    payload: dict | None = None,
    sequence: int = 0,
    event_id: str | None = None,
) -> dict:
    """构造统一 RunEvent 信封，供普通 API 与业务 SSE 复用。

    业务 SSE 中的 inline 事件不替代数据库中的 `agent_run_events`，因此默认
    sequence=0，并使用 `inline:` 前缀 event_id。
    """
    return {
        "event_id": event_id or f"inline:{run_id}:{event_type}",
        "run_id": run_id,
        "sequence": sequence,
        "type": event_type,
        "stage": stage,
        "payload": payload or {},
        "schema_version": 1,
        "timestamp": datetime.now().isoformat(),
    }
