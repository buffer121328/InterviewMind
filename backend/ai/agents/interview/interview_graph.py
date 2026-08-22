"""
面试系统 Graph 定义
实现双层架构：轻量对话 + 后台画像
支持极速响应和多维度分析

## Checkpoint 机制

本 Graph 使用 LangGraph 的 checkpoint 机制（通过 PostgresSaver/MemorySaver）支持 **退出保留进度**：

- 每个节点执行完成后，`InterviewState` 全量写入 checkpoint 表
- 下次调用时使用相同 `thread_id`，checkpointer 自动恢复到最后一个 checkpoint
- 与 Responder 内部是 ReAct 还是状态机 **完全无关** —— 这是 LangGraph 框架级别能力

### 单轮退出保留
```
用户进入面试 → thread_id="session_123"
  → node_planner 完成 → checkpoint_1 写入 PG
  → node_responder: opening → checkpoint_2
  → 用户回答第1题 → checkpoint_3
  → 用户断网/关闭浏览器

重新进入：
  → graph.ainvoke(state, config={"configurable": {"thread_id": "session_123"}})
  → PostgresSaver 加载最后一个 checkpoint
  → 面试官从断点继续
```

### 跨轮保留
```
session_1 (综合面, completed) → 基础素质画像落库
  ↓ 用户可随时查看画像和短板报告
session_2 (技术面, active)   → 读取 session_1 画像和短板
  ↓ 支持跨天/跨会话
session_3 (HR面, active)     → 读取前两轮累积画像
```
"""

import logging
import operator
import uuid
from dataclasses import dataclass
from typing import Annotated, Any, List, Literal, Mapping, Optional, TypedDict
from weakref import WeakSet

from langchain_core.messages import AIMessage, BaseMessage
from pydantic import BaseModel, Field

from ai.tools.interview_tools import (
    get_candidate_profile,
    get_interview_history,
    search_question_bank,
)
from ai.tools.memory_tools import search_memory

try:
    from langgraph.graph import END, StateGraph
    from langgraph.runtime import Runtime
except ModuleNotFoundError:  # pragma: no cover - 测试环境可无 langgraph
    StateGraph = None  # type: ignore[assignment]
    Runtime = None  # type: ignore[assignment]
    END = "__end__"

from ai.memory.memory import get_checkpointer
from app.domain.interview_round_strategy import (
    ROUND_STRATEGY_VERSION,
    round_question_type_distribution,
)

logger = logging.getLogger(__name__)


# ============================================================================
# 数据结构定义
# ============================================================================


_graph_instances: WeakSet = WeakSet()

def register_graph_instance(graph):
    """注册图实例以便后续清理"""
    _graph_instances.add(graph)
    return graph

def get_graph_instances():
    """获取所有图实例"""
    return list(_graph_instances)

def clear_graph_instances():
    """清空图实例列表"""
    _graph_instances.clear()



class InterviewQuestion(BaseModel):
    """面试问题数据模型"""
    id: int = Field(description="题目序号")
    topic: str = Field(description="考察主题，如Java并发")
    content: str = Field(description="具体的问题描述")
    type: str = Field(description="题目类型：intro, tech, behavior, system_design")
    hint: str = Field(default="", description="回答提示，帮助候选人组织回答思路")


class PlanOutput(BaseModel):
    """规划输出数据模型"""
    questions: List[InterviewQuestion]





@dataclass(frozen=True, slots=True)
class InterviewRuntimeContext:
    """不进入 checkpoint 的可信请求上下文；水合后的模型凭据只存在于此。"""

    api_config: Optional[Mapping[str, Any]] = None
    stable_context: Optional[Mapping[str, Any]] = None


class InterviewState(TypedDict):
    """数据对象，承载 `InterviewState` 的结构化字段和跨模块契约；只表达数据，不在构造或序列化时执行外部调用。
    面试状态定义 - 统一的状态结构

    用户隔离: user_id 字段从 API 层传入，贯穿整个流程，确保数据隔离。
    运行追踪: run_id 字段在每次图执行时生成，用于审计和调试。

    安全边界: 模型配置与凭据不进入本 state——由 `InterviewRuntimeContext`
    按请求传入，避免随 checkpoint 持久化。
    """

    # 消息历史
    messages: Annotated[List[BaseMessage], operator.add]

    # 基础信息
    resume_context: str
    job_description: str
    company_info: str  # 公司信息
    mode: Literal["mock"]  # 面试模式
    session_id: str  # 会话ID（用于后台分析）
    user_id: str  # 用户ID（从 API 层传入，用于数据隔离）
    run_id: str  # 运行追踪ID（每次图执行生成，UUID）

    # 规划相关
    interview_plan: List[dict]  # 存储问题清单
    current_question_index: int
    max_questions: int
    question_bank_count: int

    # 统计信息
    question_count: int  # 已完成的问题数（不含追问）
    follow_up_count: int  # 当前主线问题的追问次数
    total_follow_up_count: int  # 本轮已发出的技术追问总数

    # 阶段控制
    turn_phase: Literal["opening", "feedback"]

    # 追问控制
    current_sub_question: Optional[str]
    max_follow_ups: int

    # 轮次信息
    round_index: int
    round_type: str

    # 长期记忆上下文（来自 mem0）
    memory_context: str  # 格式化后的记忆上下文，注入到 prompt
    round_strategy_version: str
    round_question_type_distribution: dict[str, int]
    memory_items: List[dict]  # 原始记忆列表，用于日志和调试
    trace: List[dict]  # agent 运行 trace


# ============================================================================
# 节点函数
# ============================================================================

async def node_planner(state: InterviewState, runtime: Runtime[InterviewRuntimeContext]):
    """
    规划节点：生成面试题目
    使用统一的 interview_planner 模块

    上下文传递规范（文档定义 7 项固定输入）：
    1. 当前岗位 JD
    2. 当前候选人简历快照
    3. 上一轮问题列表
    4. 上一轮表现摘要（画像）
    5. 上一轮短板报告
    6. 候选人分层画像（累积）
    7. 长期记忆上下文
    """
    from .planning import planner as interview_planner

    job_desc = state["job_description"]
    resume = state["resume_context"]
    company_info = state.get("company_info", "")
    max_q = state.get("max_questions", 5)
    session_id = state.get("session_id")
    api_config = dict(runtime.context.api_config or {})
    user_id = state.get("user_id", "default_user")  # 从 state 读取 user_id
    run_id = state.get("run_id", str(uuid.uuid4()))  # 从 state 读取 run_id

    # 获取长期记忆上下文
    memory_context = state.get("memory_context", "")

    # 获取轮次信息
    round_index = 1
    round_type = "tech_initial"
    previous_profile = None
    previous_questions = []
    weakness_report = None
    previous_session_summary = None
    cache_scope = session_id or run_id

    if session_id:
        try:
            from app.db.repositories.session.session_repo import SessionRepo
            service = SessionRepo()
            session = await service.get_session(session_id, user_id=user_id)
            if session:
                round_index = session.metadata.round_index
                round_type = session.metadata.round_type
                cache_scope = getattr(session.metadata, "series_id", None) or session_id or run_id

                # 获取上一轮画像和问题（如果是第二轮及以后）
                if round_index > 1 and session.metadata.parent_session_id:
                    previous_profile = await service.get_profile(
                        session.metadata.parent_session_id,
                        user_id=user_id,
                    )
                    parent_plan = await service.get_interview_plan(session.metadata.parent_session_id)
                    if parent_plan:
                        previous_questions = [q.get("content", q.get("topic", "")) for q in parent_plan]

                    # 获取上一轮表现摘要
                    parent_session = await service.get_session(
                        session.metadata.parent_session_id, user_id=user_id
                    )
                    if parent_session and parent_session.messages:
                        # 提取最后的总结消息作为上一轮表现摘要
                        for msg in reversed(parent_session.messages):
                            if msg.role == "assistant" and len(msg.content) > 100:
                                previous_session_summary = msg.content[:500]
                                break

                    # 获取上一轮短板报告（用于多轮上下文继承）
                    try:
                        from app.db.repositories.interview.weakness_report_repo import (
                            get_weakness_report_repo,
                        )
                        weakness_service = get_weakness_report_repo()
                        weakness_report = await weakness_service.get_report_by_session(
                            session.metadata.parent_session_id,
                            user_id=user_id
                        )
                        if weakness_report:
                            weakness_report = weakness_report.get("report_data")
                    except Exception as e:
                        logger.warning(f"获取短板报告失败: {e}")
                        weakness_report = None
        except Exception as e:
            logger.error(f"获取轮次信息失败: {e}")

    # 题库题受轮次题型与优先级约束，并优先于模型生成题。
    from .questions.plan import (
        is_introduction_question,
        merge_question_plan,
        prepare_question_bank_candidates,
    )
    bank_items = []
    bank_count = min(max(int(state.get("question_bank_count", 0) or 0), 0), max_q)
    if bank_count:
        try:
            from app.db.repositories.interview.question_bank_repo import (
                get_question_bank_repo,
            )

            bank_items = await get_question_bank_repo().select_for_interview(
                user_id,
                bank_count,
                round_type=round_type,
                plan_max_questions=max_q,
            )
        except Exception as e:
            logger.warning(f"抽取个人题库失败，将由 planner 补足: {e}")
    candidates = prepare_question_bank_candidates(
        bank_items,
        max_q,
        round_type=round_type,
        selection_limit=bank_count,
        enforce_strategy=True,
    )
    known_intro_question = any(is_introduction_question(item) for item in candidates)
    remaining_questions = max_q - len(candidates)

    # 仅在仍需模型生成题目时检索上下文。
    retrieval_context = None
    if remaining_questions > 0:
        try:
            from ai.agents.interview.rag.service import (
                get_interview_retrieval_service,
            )
            retrieval_svc = get_interview_retrieval_service()
            retrieval_context = await retrieval_svc.retrieve_for_question_generation(
                user_id=user_id,
                job_description=job_desc,
                session_id=session_id,
                round_type=round_type,
                weakness_report=weakness_report,
                api_config=api_config,
            )
        except Exception as e:
            logger.warning(f"RAG 检索失败，使用默认 planner: {e}")

    # 使用统一的规划模块
    generated_plan = []
    if remaining_questions > 0:
        generated_plan = await interview_planner.generate_interview_plan(
            resume=resume,
            job_description=job_desc,
            company_info=company_info,
            max_questions=remaining_questions,
            api_config=api_config,
            round_type=round_type,
            round_index=round_index,
            previous_profile=previous_profile,
            previous_questions=previous_questions,
            known_intro_question=known_intro_question,
            output_format="full",
            session_id=session_id,
            save_to_db=False,
            generate_hints=True,
            weakness_report=weakness_report,
            retrieval_context=retrieval_context,
            memory_context=memory_context,
            previous_summary=previous_session_summary,
            owner_id=user_id,
            cache_scope=cache_scope,
            planner_tools_enabled=True,
        )
    interview_plan = merge_question_plan(
        candidates,
        generated_plan,
        max_q,
        round_type=round_type,
        enforce_strategy=True,
    )
    if session_id:
        from ai.agents.interview.turn_context import build_stable_context
        from app.db.repositories.session.session_repo import SessionRepo

        stable_context = build_stable_context(
            resume_context=resume,
            job_description=job_desc,
            company_info=company_info,
            interview_plan=interview_plan,
            round_index=round_index,
            round_type=round_type,
            memory_context=memory_context,
            rubric={
                "evaluation": ["事实依据", "技术准确性", "表达清晰度"],
                "follow_up_policy": "仅在轮次策略允许且技术主问题存在未验证缺口时追问",
            },
            prompt_version="interview-evaluating.v1",
            round_strategy_version=ROUND_STRATEGY_VERSION,
        )
        session_repo = SessionRepo()
        await session_repo.save_interview_plan(session_id, interview_plan)
        await session_repo.update_session(
            session_id=session_id,
            user_id=user_id,
            metadata_updates={
                "stable_context": stable_context.payload,
                "stable_context_version": stable_context.schema_version,
                "stable_context_fingerprint": stable_context.fingerprint,
                "round_strategy_version": ROUND_STRATEGY_VERSION,
            },
        )

    logger.info(f"[Planner] run_id={run_id} user_id={user_id} round={round_index}/{round_type} 生成 {len(interview_plan)} 题")

    return {
        "interview_plan": interview_plan,
        "current_question_index": 0,
        "question_count": 0,
        "follow_up_count": 0,
        "total_follow_up_count": 0,
        "turn_phase": "opening",
        "current_sub_question": None,
        "max_follow_ups": 2,
        "round_index": round_index,
        "round_type": round_type,
        "round_strategy_version": ROUND_STRATEGY_VERSION,
        "round_question_type_distribution": round_question_type_distribution(interview_plan),
    }


# 面试工具集（保留用于状态机在 evaluating 状态显式调用，不做 Agent 自主决策）
interview_tools = [search_question_bank, get_candidate_profile, get_interview_history, search_memory]


async def node_responder(state: InterviewState, runtime: Runtime[InterviewRuntimeContext]):
    """
    回复节点：使用 InterviewRuntime 状态机替代 ReAct agent。

    状态机流程：
      opening → asking → awaiting_reply → evaluating
        ├─ follow_up (追问 ≤ 2 次)
        ├─ advance (下一题)
        └─ end_round (本轮结束)

    每个状态调用 invoke_structured() 输出 InterviewerOutput，
    action 字段决定状态转移 —— 不再靠自然语言猜测。
    """
    from ai.llm.llm_utils import invoke_structured, invoke_structured_with_messages
    from app.config import get_settings

    from .interview_runtime import InterviewRuntime

    api_config = dict(runtime.context.api_config or {})

    # 构建 LLM 调用器：封装 invoke_structured，自动注入 api_config
    async def llm_invoker(
        prompt: str,
        output_model,
        *,
        deadline=None,
        call_metadata=None,
    ):
        """调用统一模型网关生成面试回复，并将调用结果映射为图状态。

        Args:
            prompt: 经过类型边界校验的 `prompt`；其格式和可选值由参数类型及调用流程约束。
            output_model: 经过类型边界校验的 `output_model`；其格式和可选值由参数类型及调用流程约束。
        """
        if isinstance(prompt, list):
            return await invoke_structured_with_messages(
                messages=prompt,
                output_model=output_model,
                api_config=api_config,
                channel="fast",
                max_retries=0,
                max_tokens=get_settings().interactive_interview_max_output_tokens,
                deadline=deadline,
                call_metadata=call_metadata,
            )
        return await invoke_structured(
            prompt=prompt,
            output_model=output_model,
            api_config=api_config,
            channel="fast",
            max_retries=0,
            max_tokens=get_settings().interactive_interview_max_output_tokens,
            deadline=deadline,
            call_metadata=call_metadata,
        )

    # 创建状态机
    runtime = InterviewRuntime(
        state=dict(state),
        llm_invoker=llm_invoker,
        api_config=api_config,
        stable_context=runtime.context.stable_context,
    )

    # 执行状态机主循环
    result = await runtime.run()

    # 转换消息格式（dict → AIMessage）
    messages_out = result.get("messages", [])
    langchain_messages = []
    for msg in messages_out:
        content = msg.get("content", "") if isinstance(msg, dict) else str(msg)
        langchain_messages.append(AIMessage(content=content))

    # 返回状态更新
    return {
        **result,
        "messages": langchain_messages,
        "max_questions": state.get("max_questions", 5),
    }

async def node_summary(state: InterviewState):
    """返回完成信号，不在 Graph 内抢先持久化 Session 终态。

    候选人可见结束语由 responder 输出；拥有消息、进度与 StreamDriver 生命周期的
    workflow 会在消费完 Graph 事件后统一完成 Session、归档问答并触发报告。
    """
    session_id = state.get("session_id")
    user_id = state.get("user_id", "default_user")
    run_id = state.get("run_id", "unknown")

    logger.info(
        "[Summary] run_id=%s user_id=%s session=%s 已产生完成信号",
        run_id,
        user_id,
        session_id,
    )
    return {
        "messages": [],
        "question_count": state.get("question_count"),
        "max_questions": state.get("max_questions"),
    }


# ============================================================================
# 路由逻辑
# ============================================================================

def route_entry(state: InterviewState):
    """
    入口路由：根据当前状态决定进入哪个节点
    """
    plan = state.get("interview_plan", [])

    # 如果没有计划，进入规划
    if not plan:
        return "planner"

    # 其他情况，进入 Responder 处理
    return "responder"


def route_after_responder(state: InterviewState):
    """
    Responder 之后的路由
    """
    idx = state.get("current_question_index", 0)
    plan = state.get("interview_plan", [])

    # 检查是否所有题目都问完了
    if idx >= len(plan):
        # 所有题目都问完了，去总结
        return "summary"

    # 还有题目，等待用户回答
    return END


# ============================================================================
# 图构建
# ============================================================================

async def build_interview_graph(mode: str = "mock"):
    """
    构建面试图谱
    """
    if StateGraph is None:
        raise ModuleNotFoundError("langgraph is required to build interview graph")

    workflow = StateGraph(InterviewState, context_schema=InterviewRuntimeContext)

    # 添加节点
    workflow.add_node("planner", node_planner)
    workflow.add_node("responder", node_responder)
    workflow.add_node("summary", node_summary)

    # 设置入口
    workflow.set_conditional_entry_point(
        route_entry,
        {
            "planner": "planner",
            "responder": "responder"
        }
    )

    # 规划器 -> 回答器
    workflow.add_edge("planner", "responder")

    # 回答器 -> 人工交互（或摘要）
    workflow.add_conditional_edges(
        "responder",
        route_after_responder,
        {
            END: END,
            "summary": "summary"
        }
    )


    # 摘要 -> 结束
    workflow.add_edge("summary", END)

    # 注册图实例
    checkpointer = await get_checkpointer()
    graph = workflow.compile(checkpointer=checkpointer)
    register_graph_instance(graph)

    return graph
