"""AgentRun 任务定义与前端阶段计划。"""

from app.domain.agent_definitions import get_agent_definitions
from app.domain.agent_runs import build_task_plan_from_steps

TASK_DEFINITIONS: dict[str, dict] = {
    definition.task_type: {"title": definition.title, "steps": definition.steps}
    for definition in get_agent_definitions()
}


def get_task_definition(task_type: str) -> dict:
    """获取任务类型的定义信息（标题 + 步骤列表），未知任务返回默认值。"""

    return TASK_DEFINITIONS.get(
        task_type,
        {"title": task_type, "steps": (("queued", "等待执行资源"),)},
    )


def first_running_stage(task_type: str) -> str:
    """返回任务类型第一个实际执行阶段（跳过 queued）。"""

    steps = get_task_definition(task_type)["steps"]
    return steps[1][0] if len(steps) > 1 else steps[0][0]


def build_task_plan(task_type: str, stage: str, status: str) -> list[dict]:
    """构造前端可渲染的阶段计划与状态。"""

    return build_task_plan_from_steps(
        get_task_definition(task_type)["steps"],
        stage=stage,
        status=status,
    )
