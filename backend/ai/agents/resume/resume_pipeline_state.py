"""State and state-conversion helpers for the resume pipeline graph."""

import hashlib
import json
import operator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Annotated, Any, List, Literal, Mapping, Optional, TypedDict


@dataclass
class PipelineState:
    """流水线状态，在各阶段间传递。"""

    resume_content: str
    job_description: str
    user_id: str = "default_user"
    api_config: Optional[dict] = None

    jd_analysis: Optional[dict] = None
    material_pool: Optional[dict] = None
    change_items: List[dict] = field(default_factory=list)
    assembled_resume: str = ""
    fact_check_result: Optional[dict] = None
    confirmation_items: List[dict] = field(default_factory=list)
    judge_result: Optional[dict] = None
    retry_guidance: str = ""
    retry_count: int = 0
    trace: List[dict] = field(default_factory=list)

    errors: List[str] = field(default_factory=list)


class ResumeGraphState(TypedDict, total=False):
    """可持久化的图状态；密钥和请求选项不得放在这里。"""

    resume_content: str
    job_description: str
    user_id: str
    jd_analysis: Optional[dict]
    material_pool: Optional[dict]
    change_items: List[dict]
    assembled_resume: str
    fact_check_result: Optional[dict]
    confirmation_items: List[dict]
    judge_result: Optional[dict]
    retry_guidance: str
    retry_count: int
    trace: Annotated[List[dict], operator.add]
    errors: Annotated[List[str], operator.add]


@dataclass(frozen=True, slots=True)
class ResumeRuntimeContext:
    """不进入 checkpoint 的可信请求上下文。"""

    api_config: Optional[Mapping[str, Any]] = None
    session_ids: tuple[str, ...] = ()
    include_profile: bool = False
    mode: Literal["fast", "balanced", "quality"] = "balanced"


def _pipeline_state(values: Mapping[str, Any], *, api_config: Optional[Mapping[str, Any]] = None) -> PipelineState:
    """把可持久化图状态转为旧阶段函数所需对象。"""
    return PipelineState(
        resume_content=values["resume_content"],
        job_description=values["job_description"],
        user_id=values.get("user_id", "default_user"),
        api_config=dict(api_config) if api_config else None,
        jd_analysis=values.get("jd_analysis"),
        material_pool=values.get("material_pool"),
        change_items=list(values.get("change_items", [])),
        assembled_resume=values.get("assembled_resume", ""),
        fact_check_result=values.get("fact_check_result"),
        confirmation_items=list(values.get("confirmation_items", [])),
        judge_result=values.get("judge_result"),
        retry_guidance=values.get("retry_guidance", ""),
        retry_count=values.get("retry_count", 0),
        trace=list(values.get("trace", [])),
        errors=list(values.get("errors", [])),
    )


def _graph_values(state: PipelineState, *fields: str) -> dict:
    """提取节点产物；故意排除 api_config。"""
    names = fields or (
        "resume_content",
        "job_description",
        "user_id",
        "jd_analysis",
        "material_pool",
        "change_items",
        "assembled_resume",
        "fact_check_result",
        "confirmation_items",
        "judge_result",
        "retry_guidance",
        "retry_count",
        "trace",
        "errors",
    )
    return {name: getattr(state, name) for name in names}


def _node_result(state: PipelineState, *fields: str) -> dict:
    """节点只返回本次新增的 trace/errors，避免 reducer 重复累加。"""
    result = _graph_values(state, *fields)
    result["trace"] = state.trace
    result["errors"] = state.errors
    return result


def _cache_key(stage_name: str, function: Any, values: Mapping[str, Any], fields: tuple[str, ...]) -> str:
    """缓存键只包含确定性输入；函数 id 使 monkeypatch 测试互不污染。"""
    payload = {field: values.get(field) for field in fields}
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return f"{stage_name}:{id(function)}:{digest}"


def _append_trace(
    state: PipelineState,
    step: str,
    phase: str,
    status: str,
    input_summary: Optional[str] = None,
    output_summary: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """统一记录流水线 trace。"""
    now = datetime.now(timezone.utc).isoformat()
    state.trace.append(
        {
            "step": step,
            "phase": phase,
            "status": status,
            "input_summary": input_summary,
            "output_summary": output_summary,
            "error": error,
            "started_at": now,
            "finished_at": now,
        }
    )
