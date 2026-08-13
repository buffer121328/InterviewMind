"""AgentRun 队列与恢复策略的环境配置读取。"""

import os


def task_queue_enabled() -> bool:
    """判断是否启用异步任务队列。"""

    return os.getenv("TASK_QUEUE_ENABLED", "true").lower() == "true"


def max_attempts() -> int:
    """返回 AgentRun 最大重试次数。"""

    return max(1, int(os.getenv("AGENT_RUN_MAX_ATTEMPTS", "3")))


def stale_after_seconds() -> int:
    """返回 AgentRun 被视为卡住的超时秒数。"""

    return max(60, int(os.getenv("AGENT_RUN_STALE_SECONDS", "1800")))
