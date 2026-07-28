"""BOSS 直聘确定性工作流。模型只负责结构化提取和语义评分。"""

import asyncio
import logging
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from ai.runtime.context import AgentContext
from ai.tools import ToolExecutionGuard, ToolExecutionPolicy
from ai.tools import boss_tools
from observability import langgraph_langfuse_scope, with_langgraph_langfuse_config

logger = logging.getLogger(__name__)

class BossSearchState(TypedDict, total=False):
    """数据对象，承载 `BossSearchState` 的结构化字段和跨模块契约；只表达数据，不在构造或序列化时执行外部调用。"""
    query: str
    city: str
    top_n: int
    environment: str
    cards: List[Dict[str, Any]]
    processed: List[Dict[str, Any]]
    error: str


def _build_boss_graph(
    *, user_id: str, resume_content: str, api_config: dict, guard: ToolExecutionGuard, audit_events: list[dict[str, Any]]
):
    """构造一次请求专用的图；密钥留在闭包中，不进入 state/checkpoint。"""
    context = AgentContext(
        user_id=user_id,
        permissions=frozenset({
            "jobs:automate",
            "jobs.environment.read",
            "boss.browser.read",
            "jobs.cards.extract",
            "jobs.score",
            "jobs.capture.write",
            "jobs.assets.write",
        }),
    )

    async def execute_tool(
        contract_name: str,
        call: Any,
        *args: Any,
        confirmed: bool = False,
        audit_callback: Any = None,
        **kwargs: Any,
    ) -> Any:
        """在当前用户上下文中执行 BOSS 工具，统一应用权限、人工确认、审计和工具副作用策略。"""
        contract = boss_tools.get_boss_tool_contract(contract_name)
        return await guard.execute(
            call,
            *args,
            context=context,
            effect=contract.effect,
            required_permissions=contract.permissions,
            requires_confirmation=contract.requires_confirmation,
            confirmed=confirmed,
            tool_name=contract_name,
            audit_callback=audit_callback,
            **kwargs,
        )

    def record_audit(event: dict[str, Any]) -> None:
        """记录 `audit`。

        Args:
            event: 事件对象。
        """
        audit_events.append(event)

    async def check_environment(state: BossSearchState) -> dict:
        """检查 `environment`。

        Args:
            state: 当前流程状态。
        """
        result = await execute_tool(
            "check_environment",
            boss_tools.check_environment,
            audit_callback=record_audit,
        )
        error = "" if result.startswith("✅") else result
        return {"environment": result, "error": error}

    def after_environment(state: BossSearchState) -> str:
        """根据环境检查结果决定继续读取页面还是安全结束 BOSS 流程。

        Args:
            state: 当前流程状态。
        """
        return "finish" if state.get("error") else "open_page"

    async def acquire_cards(state: BossSearchState) -> dict:
        """读取 BOSS 搜索结果并提取岗位卡片，失败时写入工作流错误而不继续评分。

        Args:
            state: 当前流程状态。
        """
        page_text = await execute_tool(
            "open_boss_search_page",
            boss_tools.open_boss_search_page,
            state["query"],
            state.get("city", ""),
            confirmed=True,  # 调用此接口即确认本次搜索，不授权投递或发消息。
            audit_callback=record_audit,
        )
        error = page_text if page_text.startswith(("ERROR:", "CAPTCHA:")) else ""
        if error:
            return {"cards": [], "error": error}
        cards = await execute_tool(
            "extract_job_cards_from_page",
            boss_tools.extract_job_cards_from_page,
            page_text,
            top_n=15,
            query_filter=state["query"],
            api_config=api_config,
            audit_callback=record_audit,
        )
        return {"cards": cards, "error": "" if cards else "未提取到岗位"}

    def after_acquire(state: BossSearchState) -> str:
        """根据岗位卡片获取结果选择评分或结束分支。

        Args:
            state: 当前流程状态。
        """
        return "finish" if state.get("error") else "score"

    async def score(state: BossSearchState) -> dict:
        """对岗位卡片进行匹配评分，输入简历和模型配置只在当前请求上下文中使用。

        Args:
            state: 当前流程状态。
        """
        cards = await execute_tool(
            "score_jobs_by_match",
            boss_tools.score_jobs_by_match,
            state["cards"],
            resume_content,
            query=state["query"],
            api_config=api_config,
            audit_callback=record_audit,
        )
        return {"cards": cards[: state["top_n"]]}

    async def _process_card(card: Dict[str, Any]) -> Dict[str, Any]:
        """处理 card，将单项结果映射为可审计的流程状态，并隔离单项失败对整体任务的影响。

        Args:
            card: 经过类型边界校验的 `card`；其格式和可选值由参数类型及调用流程约束。
        """
        saved = await execute_tool(
            "save_job_to_database",
            boss_tools.save_job_to_database,
            card,
            user_id,
            audit_callback=record_audit,
        )
        result = {"card": card, "save": saved}
        job_id = saved.get("job_id")
        if saved.get("success") and job_id and not saved.get("is_duplicate"):
            result["assets"] = await execute_tool(
                "generate_job_assets",
                boss_tools.generate_job_assets,
                job_id,
                user_id,
                resume_content,
                api_config,
                audit_callback=record_audit,
            )
        return result

    async def persist(state: BossSearchState) -> dict:
        """持久化当前阶段结果和审计信息；外部写入失败不应泄露敏感载荷。

        Args:
            state: 当前流程状态。
        """
        processed = await asyncio.gather(*(_process_card(card) for card in state["cards"]))
        return {"processed": processed}

    async def finish(state: BossSearchState) -> dict:
        """完成 BOSS 工作流的状态收尾，返回可展示结果并保留工具审计事件。

        Args:
            state: 当前流程状态。
        """
        return {}

    workflow = StateGraph(BossSearchState)
    workflow.add_node("check_environment", check_environment)
    workflow.add_node("acquire_cards", acquire_cards)
    workflow.add_node("score", score)
    workflow.add_node("persist", persist)
    workflow.add_node("finish", finish)
    workflow.add_edge(START, "check_environment")
    workflow.add_conditional_edges(
        "check_environment", after_environment, {"open_page": "acquire_cards", "finish": "finish"}
    )
    workflow.add_conditional_edges(
        "acquire_cards", after_acquire, {"score": "score", "finish": "finish"}
    )
    workflow.add_edge("score", "persist")
    workflow.add_edge("persist", "finish")
    workflow.add_edge("finish", END)
    return workflow


async def run_boss_search(
    user_id: str,
    query: str,
    resume_content: str,
    api_config: Optional[dict] = None,
    top_n: int = 5,
    city: str = "",
) -> Dict[str, Any]:
    """执行固定 BOSS 搜索流程，保持原 API 返回结构。"""
    if not api_config:
        return {"success": False, "total": 0, "jobs": [], "message": "未配置 API"}

    from ai.memory.memory import get_checkpointer

    guard = ToolExecutionGuard(
        ToolExecutionPolicy(timeout_seconds=240, max_calls=4 + max(0, top_n) * 2, max_retries=1)
    )
    audit_events: list[dict[str, Any]] = []
    workflow = _build_boss_graph(
        user_id=user_id,
        resume_content=resume_content,
        api_config=api_config,
        guard=guard,
        audit_events=audit_events,
    )
    graph = workflow.compile(checkpointer=await get_checkpointer())
    try:
        graph_config = with_langgraph_langfuse_config(
            {"configurable": {"thread_id": f"boss_{user_id}"}},
            run_name="boss-job-discovery",
            metadata={"agent_type": "boss", "user_id": user_id, "city": city},
        )
        with langgraph_langfuse_scope("callbacks" in graph_config):
            result = await graph.ainvoke(
                {"query": query, "city": city, "top_n": max(1, min(top_n, 10))},
                config=graph_config,
            )
        processed = result.get("processed", [])
        jobs = [
            {
                "job_id": item.get("save", {}).get("job_id"),
                "company_name": item["card"].get("company_name", ""),
                "job_title": item["card"].get("job_title", ""),
                "salary_text": item["card"].get("salary_text", ""),
                "city": item["card"].get("city", ""),
                "status": "pending",
            }
            for item in processed
            if item.get("save", {}).get("success")
        ]
        error = result.get("error", "")
        return {
            "success": not error,
            "total": len(jobs),
            "jobs": jobs,
            "message": error or f"搜索完成，处理 {len(jobs)} 个岗位",
            "audit_events": audit_events,
        }
    except Exception as exc:
        logger.error("[BossGraph] 执行失败: %s", exc, exc_info=True)
        return {"success": False, "total": 0, "jobs": [], "message": f"Agent 执行失败: {exc}"}
