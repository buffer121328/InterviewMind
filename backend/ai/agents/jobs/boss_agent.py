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

BOSS_AGENT_SYSTEM_PROMPT = """BOSS 求职工作流按固定步骤执行：环境检查、页面读取、岗位提取、匹配评分、保存和资产生成。"""


class BossSearchState(TypedDict, total=False):
    """表示 `BossSearchState` 的字典状态结构。"""
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
        permissions=frozenset({"jobs:automate"}),
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
        result = await guard.execute(
            boss_tools.check_environment,
            context=context,
            effect="read",
            audit_callback=record_audit,
            tool_name="check_environment",
        )
        error = "" if result.startswith("✅") else result
        return {"environment": result, "error": error}

    def after_environment(state: BossSearchState) -> str:
        """执行 `after_environment` 相关逻辑。

        Args:
            state: 当前流程状态。
        """
        return "finish" if state.get("error") else "open_page"

    async def acquire_cards(state: BossSearchState) -> dict:
        """异步执行 `acquire_cards` 相关逻辑。

        Args:
            state: 当前流程状态。
        """
        page_text = await guard.execute(
            boss_tools.open_boss_search_page,
            state["query"],
            state.get("city", ""),
            context=context,
            effect="external",
            required_permissions={"jobs:automate"},
            requires_confirmation=True,
            confirmed=True,  # 调用此接口即确认本次搜索，不授权投递或发消息。
        )
        error = page_text if page_text.startswith(("ERROR:", "CAPTCHA:")) else ""
        if error:
            return {"cards": [], "error": error}
        cards = await guard.execute(
            boss_tools.extract_job_cards_from_page,
            page_text,
            top_n=15,
            query_filter=state["query"],
            api_config=api_config,
            context=context,
            effect="read",
            audit_callback=record_audit,
            tool_name="extract_job_cards_from_page",
        )
        return {"cards": cards, "error": "" if cards else "未提取到岗位"}

    def after_acquire(state: BossSearchState) -> str:
        """执行 `after_acquire` 相关逻辑。

        Args:
            state: 当前流程状态。
        """
        return "finish" if state.get("error") else "score"

    async def score(state: BossSearchState) -> dict:
        """异步执行 `score` 相关逻辑。

        Args:
            state: 当前流程状态。
        """
        cards = await guard.execute(
            boss_tools.score_jobs_by_match,
            state["cards"],
            resume_content,
            query=state["query"],
            api_config=api_config,
            context=context,
            effect="read",
            audit_callback=record_audit,
            tool_name="score_jobs_by_match",
        )
        return {"cards": cards[: state["top_n"]]}

    async def _process_card(card: Dict[str, Any]) -> Dict[str, Any]:
        """处理 `card`。

        Args:
            card: 调用方传入的 `card` 参数。
        """
        saved = await guard.execute(
            boss_tools.save_job_to_database,
            card,
            user_id,
            context=context,
            effect="write",
            required_permissions={"jobs:automate"},
            audit_callback=record_audit,
            tool_name="save_job_to_database",
        )
        result = {"card": card, "save": saved}
        job_id = saved.get("job_id")
        if saved.get("success") and job_id and not saved.get("is_duplicate"):
            result["assets"] = await guard.execute(
                boss_tools.generate_job_assets,
                job_id,
                user_id,
                resume_content,
                api_config,
                context=context,
                effect="write",
                required_permissions={"jobs:automate"},
                audit_callback=record_audit,
                tool_name="generate_job_assets",
            )
        return result

    async def persist(state: BossSearchState) -> dict:
        """异步执行 `persist` 相关逻辑。

        Args:
            state: 当前流程状态。
        """
        processed = await asyncio.gather(*(_process_card(card) for card in state["cards"]))
        return {"processed": processed}

    async def finish(state: BossSearchState) -> dict:
        """异步执行 `finish` 相关逻辑。

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
