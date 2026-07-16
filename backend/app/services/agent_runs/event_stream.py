"""AgentRun 事件流重放契约。"""


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
