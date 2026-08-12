"""Production Agent 图与通用 runtime 注册表的组合绑定。"""

from __future__ import annotations

from threading import RLock
from typing import Any

from ai.runtime.graphs import GraphSpec, graph_registry

_REGISTERED = False
_REGISTRATION_LOCK = RLock()


async def _build_interview(**kwargs: Any) -> Any:
    """延迟构建面试图，避免 runtime 导入业务 Agent。"""

    from ai.agents.interview.graph import build_interview_graph

    return await build_interview_graph(**kwargs)


def _build_resume_analyzer(**kwargs: Any) -> Any:
    """延迟构建简历分析图。"""

    from ai.agents.resume.resume_analyzer_graph import build_resume_analyzer_graph

    return build_resume_analyzer_graph(**kwargs)


def _build_resume_optimizer(**kwargs: Any) -> Any:
    """延迟构建简历优化图。"""

    from ai.agents.resume.optimization.flow import build_resume_optimizer_graph

    return build_resume_optimizer_graph(**kwargs)


def _build_resume_generator(**kwargs: Any) -> Any:
    """延迟构建简历生成图。"""

    from ai.agents.resume.generation.graph import build_resume_generation_graph

    return build_resume_generation_graph(**kwargs)


def register_production_graphs() -> None:
    """注册 production catalog 所需的业务图绑定。"""

    global _REGISTERED
    with _REGISTRATION_LOCK:
        if _REGISTERED:
            return
        graph_registry.register(GraphSpec("interview", "1", _build_interview))
        graph_registry.register(GraphSpec("resume_analyzer", "1", _build_resume_analyzer))
        graph_registry.register(GraphSpec("resume_optimizer", "1", _build_resume_optimizer))
        graph_registry.register(GraphSpec("resume_generator", "1", _build_resume_generator))
        _REGISTERED = True
