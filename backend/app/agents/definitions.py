"""项目中已投入生产使用的 Agent 定义。"""

from app.infrastructure.runtime.definitions import AgentDefinition, agent_definition_registry

_DEFINITIONS = (
    AgentDefinition(
        name="interview_starter",
        version="1",
        task_type="interview_start",
        title="生成面试首题",
        steps=(("queued", "等待执行资源"), ("loading_context", "读取简历与面试上下文"), ("generating_question", "规划面试并生成首题")),
        checkpoint_policy="durable",
        graph_name="interview",
        prompt_name="interview.planner",
        prompt_version="1",
    ),
    AgentDefinition(
        name="interview_turn",
        version="1",
        task_type="interview_turn",
        title="生成面试追问与反馈",
        steps=(
            ("queued", "等待执行资源"),
            ("loading_session", "读取面试会话与上下文"),
            ("saving_answer", "记录本轮回答"),
            ("generating_response", "生成反馈与下一题"),
            ("saving_response", "保存面试进度与回复"),
        ),
        checkpoint_policy="durable",
        graph_name="interview",
        prompt_name="interview.evaluating",
        prompt_version="1",
    ),
    AgentDefinition(
        name="voice_interview_turn",
        version="1",
        task_type="voice_interview_turn",
        title="生成语音面试回复",
        steps=(
            ("queued", "等待执行资源"),
            ("transcribing", "识别语音或读取文本"),
            ("generating_response", "生成语音面试回复"),
            ("streaming_response", "推送语音回复"),
        ),
        checkpoint_policy="durable",
        graph_name="interview",
        prompt_name="voice.system",
        prompt_version="1",
    ),
    AgentDefinition(
        name="resume_optimizer",
        version="1",
        task_type="resume_optimize",
        title="优化简历",
        steps=(("queued", "等待执行资源"), ("preparing", "读取简历、JD 与关联面试"), ("optimizing", "执行简历优化流水线"), ("saving_result", "保存优化结果")),
        graph_name="resume_optimizer",
        prompt_name="resume.match_analyst",
        prompt_version="1",
    ),
    AgentDefinition(
        name="interview_reporter",
        version="1",
        task_type="interview_report",
        title="生成面试报告",
        steps=(("queued", "等待执行资源"), ("loading_session", "读取面试问答"), ("generating_profile", "生成本轮能力画像"), ("generating_weakness", "生成短板地图"), ("saving_report", "保存报告")),
        graph_name="interview",
        prompt_name="analysis.weakness_report",
        prompt_version="1",
    ),
    AgentDefinition(
        name="job_asset_builder",
        version="1",
        task_type="job_assets",
        title="生成岗位投递资产",
        steps=(("queued", "等待执行资源"), ("loading_job", "读取岗位与候选人资料"), ("analyzing_jd", "分析岗位匹配度"), ("generating_assets", "生成定制简历与招呼文案"), ("saving_assets", "保存岗位资产")),
        graph_name="resume_generator",
        prompt_name="resume.jd_match.user",
        prompt_version="1",
    ),
)

for _definition in _DEFINITIONS:
    agent_definition_registry.register(_definition)


def get_agent_definition(task_type: str) -> AgentDefinition:
    return agent_definition_registry.get(task_type)


def get_agent_definitions() -> tuple[AgentDefinition, ...]:
    return agent_definition_registry.definitions()
