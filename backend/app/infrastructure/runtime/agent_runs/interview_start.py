"""兼容旧路径的面试首题执行器导出。

业务实现已移动到 ``app.workflows.agent_tasks.interview_start``。
"""

from app.workflows.agent_tasks.interview_start import execute_interview_start

__all__ = ["execute_interview_start"]
