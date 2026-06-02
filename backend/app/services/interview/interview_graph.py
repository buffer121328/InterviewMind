"""
面试系统 Graph 定义
实现双层架构：轻量对话 + 后台画像
支持极速响应和多维度分析
"""

import asyncio
import json
import logging
import operator
import re
from typing import Annotated, List, Literal, TypedDict, Optional
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, BaseMessage
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import create_react_agent
from app.services import llms
from app.services.memory import get_async_sqlite_saver
from app.services.tools.interview_tools import search_question_bank, get_candidate_profile, get_interview_history
from app.services.tools.memory_tools import search_memory
from .mode_strategy import ModeStrategyFactory

logger = logging.getLogger(__name__)


# ============================================================================
# 数据结构定义
# ============================================================================


_graph_instances = []

def register_graph_instance(graph):
    """注册图实例以便后续清理"""
    _graph_instances.append(graph)
    return graph

def get_graph_instances():
    """获取所有图实例"""
    return _graph_instances

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





class InterviewState(TypedDict):
    """
    面试状态定义 - 统一的状态结构
    """

    # 消息历史
    messages: Annotated[List[BaseMessage], operator.add]

    # 基础信息
    resume_context: str
    job_description: str
    company_info: str  # 公司信息
    mode: Literal["mock"]  # 面试模式
    session_id: str  # 会话ID（用于后台分析）

    # 规划相关
    interview_plan: List[dict]  # 存储问题清单
    current_question_index: int
    max_questions: int

    # 统计信息
    question_count: int  # 已完成的问题数（不含追问）
    follow_up_count: int  # 当前主线问题的追问次数
    
    # 阶段控制
    turn_phase: Literal["opening", "feedback"]
    
    # 追问控制
    current_sub_question: Optional[str]
    max_follow_ups: int
    
    # 用户 API 配置（可选）
    api_config: Optional[dict]
    
    # 轮次信息
    round_index: int
    round_type: str
    
    # 长期记忆上下文（来自 mem0）
    memory_context: str  # 格式化后的记忆上下文，注入到 prompt
    memory_items: List[dict]  # 原始记忆列表，用于日志和调试


# ============================================================================
# 节点函数
# ============================================================================

async def node_planner(state: InterviewState):
    """
    规划节点：生成面试题目
    使用统一的 interview_planner 模块
    """
    from . import interview_planner
    
    job_desc = state["job_description"]
    resume = state["resume_context"]
    company_info = state.get("company_info", "")
    max_q = state.get("max_questions", 5)
    session_id = state.get("session_id")
    api_config = state.get("api_config") or {}
    
    # 获取长期记忆上下文
    memory_context = state.get("memory_context", "")
    
    # 获取轮次信息
    round_index = 1
    round_type = "tech_initial"
    previous_profile = None
    previous_questions = []
    weakness_report = None
    
    if session_id:
        try:
            from app.repositories.session.session_repo import SessionRepo
            service = SessionRepo()
            session = await service.get_session(session_id)
            if session:
                round_index = session.metadata.round_index
                round_type = session.metadata.round_type
                
                # 获取上一轮画像和问题（如果是第二轮及以后）
                if round_index > 1 and session.metadata.parent_session_id:
                    previous_profile = await service.get_profile(session.metadata.parent_session_id)
                    parent_plan = await service.get_interview_plan(session.metadata.parent_session_id)
                    if parent_plan:
                        previous_questions = [q.get("content", q.get("topic", "")) for q in parent_plan]
                    
                    # 获取上一轮短板报告（用于多轮上下文继承）
                    try:
                        from app.repositories.interview.weakness_report_repo import get_weakness_report_repo
                        weakness_service = get_weakness_report_repo()
                        weakness_report = await weakness_service.get_report_by_session(
                            session.metadata.parent_session_id
                        )
                        if weakness_report:
                            weakness_report = weakness_report.get("report_data")
                    except Exception as e:
                        logger.warning(f"获取短板报告失败: {e}")
                        weakness_report = None
        except Exception as e:
            logger.error(f"获取轮次信息失败: {e}")

    # 检索上下文（RAG 编排：rag_chunks + pgvector，降级到直接查询）
    retrieval_context = None
    try:
        from app.repositories.interview.retrieval_repo import get_retrieval_repo
        retrieval_svc = get_retrieval_repo()
        retrieval_context = await retrieval_svc.retrieve_for_question_generation(
            user_id="default_user",
            job_description=job_desc,
            session_id=session_id,
            round_type=round_type,
            weakness_report=weakness_report,
        )
    except Exception as e:
        logger.warning(f"RAG 检索失败，使用默认 planner: {e}")
    
    # 使用统一的规划模块
    interview_plan = await interview_planner.generate_interview_plan(
        resume=resume,
        job_description=job_desc,
        company_info=company_info,
        max_questions=max_q,
        api_config=api_config,
        round_type=round_type,
        round_index=round_index,
        previous_profile=previous_profile,
        previous_questions=previous_questions,
        output_format="full",
        session_id=session_id,
        save_to_db=True,
        generate_hints=True,
        weakness_report=weakness_report,
        retrieval_context=retrieval_context,
        memory_context=memory_context,  # 传递长期记忆上下文
    )
    
    return {
        "interview_plan": interview_plan,
        "current_question_index": 0,
        "question_count": 0,
        "follow_up_count": 0,
        "turn_phase": "opening",
        "current_sub_question": None,
        "max_follow_ups": 2,
        "round_index": round_index,
        "round_type": round_type
    }


interview_tools = [search_question_bank, get_candidate_profile, get_interview_history, search_memory]


def _build_interview_agent_prompt(state: InterviewState) -> str:
    """构建面试官 Agent 的系统提示"""
    idx = state.get("current_question_index", 0)
    plan = state.get("interview_plan", [])
    turn_phase = state.get("turn_phase", "opening")
    round_index = state.get("round_index", 1)
    round_type = state.get("round_type", "tech_initial")
    memory_context = state.get("memory_context", "")

    from .interview_planner import ROUND_STRATEGIES
    strategy = ROUND_STRATEGIES.get(round_type, ROUND_STRATEGIES["tech_initial"])
    focus = strategy["focus"]

    current_question = plan[idx]["content"] if idx < len(plan) else ""
    next_question = plan[idx + 1]["content"] if idx + 1 < len(plan) else ""

    system_prompt = f"""你是一位专业的技术面试官。
今天是第 {round_index} 轮面试（侧重：{focus}）。

【当前面试进度】：
- 当前题目索引: {idx + 1}/{len(plan)}
- 当前阶段: {'开场' if turn_phase == 'opening' else '答题反馈'}

【当前题目】：{current_question}
【下一题目】：{next_question if next_question else '已是最后一题'}

【你的职责】：
1. 如果是开场阶段：输出问候语并提出第一道题目
2. 如果是反馈阶段：
   - 简要评价候选人的回答（一句话即可）
   - 你可以使用工具查询题库、候选人画像或记忆来决定是否追问
   - 如果候选人回答不够深入，可以追问（最多2次）
   - 如果回答充分，自然过渡到下一题；进入下一题时必须完整复述【下一题目】原文，便于系统识别进度

【可用工具】：
- search_question_bank: 搜索题库获取相关问题
- get_candidate_profile: 获取候选人历史能力画像
- get_interview_history: 获取面试历史记录
- search_memory: 搜索候选人长期记忆

请直接输出你的回复，不要输出"回复："等前缀。"""

    if memory_context:
        system_prompt = f"""{memory_context}

{system_prompt}"""

    return system_prompt


def _classify_responder_action(response_content: str, current_question: str, next_question: str) -> str:
    """
    判断面试官回复是在追问当前题，还是进入下一题。

    旧逻辑只匹配「追问」等少量关键词，容易在面试官自然追问时误推进。
    新逻辑优先判断是否明确包含下一题；如果回复包含问号但不是下一题，则视为追问。
    """
    normalized = (response_content or "").strip()
    if not normalized:
        return "next_question"

    if next_question and next_question.strip() and next_question.strip() in normalized:
        return "next_question"

    follow_up_markers = (
        "追问", "详细说说", "再解释", "展开", "为什么", "具体", "举个例子",
        "能否", "可以说说", "怎么做", "如何", "哪一步", "什么原因"
    )
    has_question = any(mark in normalized for mark in ("？", "?"))
    has_follow_marker = any(marker in normalized for marker in follow_up_markers)

    if has_question or has_follow_marker:
        return "follow_up"

    return "next_question"


async def node_responder(state: InterviewState):
    """
    回复节点：使用 create_react_agent 实现动态面试
    """
    api_config = state.get("api_config")
    fast_llm = llms.get_llm_for_request(api_config, channel="fast")

    idx = state.get("current_question_index", 0)
    plan = state.get("interview_plan", [])
    turn_phase = state.get("turn_phase", "opening")
    messages = state.get("messages", [])

    system_prompt = _build_interview_agent_prompt(state)

    agent = create_react_agent(
        model=fast_llm,
        tools=interview_tools,
        prompt=system_prompt,
    )

    if turn_phase == "opening":
        agent_input = {"messages": [HumanMessage(content="请开始面试，输出问候语并提出第一道题目。")]} 
    else:
        user_response = messages[-1].content if messages else ""
        current_question = plan[idx]["content"] if idx < len(plan) else ""
        agent_input = {"messages": [HumanMessage(content=f"候选人回答了问题「{current_question}」：\n{user_response}")]} 

    result = await agent.ainvoke(agent_input)

    agent_messages = result.get("messages", [])
    if agent_messages:
        last_message = agent_messages[-1]
        response_content = last_message.content if hasattr(last_message, 'content') else str(last_message)
    else:
        response_content = "请继续回答下一道题目。"

    response = AIMessage(content=response_content)

    next_idx = idx + 1 if turn_phase == "feedback" else idx

    follow_up_count = state.get("follow_up_count", 0)
    max_follow_ups = state.get("max_follow_ups", 2)
    current_question = plan[idx]["content"] if idx < len(plan) else ""
    next_question = plan[idx + 1]["content"] if idx + 1 < len(plan) else ""
    is_follow_up = _classify_responder_action(response_content, current_question, next_question) == "follow_up"

    if is_follow_up and follow_up_count < max_follow_ups:
        return {
            "messages": [response],
            "follow_up_count": follow_up_count + 1,
            "current_sub_question": response_content,
            "turn_phase": "feedback"
        }
    else:
        return {
            "messages": [response],
            "current_question_index": next_idx,
            "question_count": next_idx,
            "current_sub_question": None,
            "follow_up_count": 0,
            "max_questions": state.get("max_questions", 5),
            "turn_phase": "feedback"
        }

async def node_summary(state: InterviewState):
    """
    总结节点：生成面试报告
    使用统一的 interview_analysis 模块
    """
    from . import interview_analysis
    from langchain_core.messages import AIMessage
    
    mode = state.get("mode", "mock")
    session_id = state.get("session_id")
    api_config = state.get("api_config")
    
    # 获取长期记忆上下文
    memory_context = state.get("memory_context", "")
    
    # 执行统一流程（生成文本 + 状态更新 + 画像分析）
    summary = await interview_analysis.process_interview_summary(
        session_id=session_id,
        messages=state["messages"],
        mode=mode,
        api_config=api_config,
        trigger_analysis=True,
        memory_context=memory_context,  # 传递长期记忆上下文
    )
    
    return {
        "messages": [AIMessage(content=summary)],
        "question_count": state.get("question_count"),
        "max_questions": state.get("max_questions")
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
    workflow = StateGraph(InterviewState)
    
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
    
    # Planner -> Responder
    workflow.add_edge("planner", "responder")
    
    # Responder -> Human (or Summary)
    workflow.add_conditional_edges(
        "responder",
        route_after_responder,
        {
            END: END,
            "summary": "summary"
        }
    )

    
    # Summary -> END
    workflow.add_edge("summary", END)
    
    # 注册图实例
    checkpointer = await get_async_sqlite_saver()
    graph = workflow.compile(checkpointer=checkpointer)
    register_graph_instance(graph)
    
    return graph
