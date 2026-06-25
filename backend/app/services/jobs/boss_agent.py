"""
BOSS 直聘 ReAct Agent — 基于 LangGraph create_react_agent 实现
"""

import logging
from typing import Optional, Dict, Any, List

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from app.services import llms
from app.services.jobs import boss_tools as _tools

logger = logging.getLogger(__name__)

BOSS_AGENT_SYSTEM_PROMPT = """你是一个 BOSS 直聘求职助手 Agent。帮用户搜索岗位、提取信息、保存岗位、生成投递资产。

## 可用工具
**check_environment** — 检测环境是否支持自动化（先调用）
**open_boss_search_page(query, city)** — 打开 BOSS 搜索页读取内容
**extract_job_cards(page_text, top_n, query_filter)** — 从搜索页提取岗位卡片列表
**score_jobs(cards)** — 对岗位列表做匹配度打分排序
**save_job(card_data)** — 保存岗位到数据库（含去重）
**generate_assets(job_id)** — 为岗位生成投递资产

## 标准工作流
1. check_environment
2. open_boss_search_page
3. extract_job_cards
4. score_jobs
5. 对前 N 个岗位逐个 save_job + generate_assets
6. 汇总结果

## 异常处理
- CAPTCHA → 告知用户需手动验证
- ERROR → 告知具体错误
- 空列表 → 建议调整搜索词
- is_duplicate → 跳过
- generate_assets 失败 → 记录但继续

最终回复需包含清晰摘要：搜索到多少、成功处理多少、Top3 岗位名和匹配度。全程使用中文。"""


def _make_tools(user_id: str, api_config: Optional[dict], resume_content: str) -> list:
    @tool
    async def open_boss_search_page(query: str, city: str = "") -> str:
        """打开 BOSS 直聘搜索页，返回页面文本"""
        return await _tools.open_boss_search_page(query=query, city=city)

    @tool
    async def extract_job_cards(page_text: str, top_n: int = 10, query_filter: str = "") -> list:
        """从搜索页文本中提取岗位卡片列表"""
        return await _tools.extract_job_cards_from_page(page_text=page_text, top_n=top_n,
                                                        query_filter=query_filter, api_config=api_config)

    @tool
    async def score_jobs(cards: List[Dict[str, Any]]) -> list:
        """对岗位列表做匹配度打分，按分数降序排列"""
        return await _tools.score_jobs_by_match(cards=cards, resume_content=resume_content,
                                                api_config=api_config)

    @tool
    async def save_job(card_data: Dict[str, Any]) -> Dict[str, Any]:
        """保存单个岗位到数据库"""
        return await _tools.save_job_to_database(raw_data=card_data, user_id=user_id, platform="boss")

    @tool
    async def generate_assets(job_id: int) -> Dict[str, Any]:
        """为岗位生成投递资产"""
        return await _tools.generate_job_assets(job_id=job_id, user_id=user_id,
                                                resume_content=resume_content, api_config=api_config)

    @tool
    async def check_environment() -> str:
        """检测当前环境"""
        return await _tools.check_environment()

    return [check_environment, open_boss_search_page, extract_job_cards, score_jobs, save_job, generate_assets]


async def run_boss_search(user_id: str, query: str, resume_content: str,
                          api_config: Optional[dict] = None, top_n: int = 5,
                          city: str = "") -> Dict[str, Any]:
    """运行 BOSS 直聘 Agent 搜索 — ReAct 版本"""
    if not api_config:
        return {"success": False, "total": 0, "jobs": [], "message": "未配置 API"}

    city_hint = f"，城市：{city}" if city else "（城市不限）"
    user_message = f"请帮我在 BOSS 直聘上搜索「{query}」岗位{city_hint}。提取前15个卡片，匹配度排序后为前{top_n}个生成投递资产。跳过重复岗位。\n我的简历：\n{resume_content[:500]}"

    try:
        agent_llm = llms.get_llm_for_request(api_config, channel="smart")
        agent_llm.max_tokens = 4000
        tools = _make_tools(user_id=user_id, api_config=api_config, resume_content=resume_content)
        agent = create_react_agent(model=agent_llm, tools=tools, prompt=BOSS_AGENT_SYSTEM_PROMPT)
        logger.info(f"[BossAgent] 开始搜索: query={query!r}")

        messages = [HumanMessage(content=user_message)]
        result = await agent.ainvoke({"messages": messages},
                                     config={"configurable": {"thread_id": f"boss_{user_id}"}})

        agent_messages = result.get("messages", [])
        agent_response = ""
        for msg in reversed(agent_messages):
            content = getattr(msg, "content", "") if hasattr(msg, "content") else str(msg)
            if content and not isinstance(msg, HumanMessage):
                agent_response = content
                break

        from app.repositories.jobs.job_capture_repo import get_job_capture_repo
        repo = get_job_capture_repo()
        recent_jobs = await repo.list_jobs(user_id=user_id, platform="boss", limit=top_n * 2)
        jobs = [{"job_id": j.get("id"), "company_name": j.get("company_name", ""),
                 "job_title": j.get("job_title", ""), "salary_text": j.get("salary_text", ""),
                 "city": j.get("city", ""), "status": j.get("status", "pending")}
                for j in (recent_jobs or [])[:top_n]]

        logger.info(f"[BossAgent] 完成: {len(jobs)} 岗位")
        return {"success": True, "total": len(jobs), "jobs": jobs,
                "message": agent_response[:1000] if agent_response else "搜索完成",
                "agent_response": agent_response}
    except Exception as e:
        logger.error(f"[BossAgent] 失败: {e}", exc_info=True)
        return {"success": False, "total": 0, "jobs": [], "message": f"Agent 执行失败: {e}"}
