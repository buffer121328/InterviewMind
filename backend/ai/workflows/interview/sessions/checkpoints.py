"""交互式面试 checkpoint 命名规则。"""


def interview_turn_checkpoint_thread_id(session_id: str, run_id: str) -> str:
    """为一次面试生成 Run 生成稳定 checkpoint thread_id。"""
    return f"interview:{session_id}:run:{run_id}"
