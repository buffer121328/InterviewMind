"""
岗位相关工具工厂
"""

from typing import Any, Dict, List, Optional

from langchain_core.tools import tool

from app.agent_runtime.tool_contracts import attach_tool_contract

from app.services.jobs import boss_tools as _tools


def make_jobs_tools(user_id: str, api_config: Optional[dict], resume_content: str) -> List[Any]:
    """构造绑定用户上下文的岗位工具集合。"""

    @tool
    async def open_boss_search_page(query: str, city: str = "") -> str:
        """打开 BOSS 搜索页，返回页面文本。"""
        return await _tools.open_boss_search_page(query=query, city=city)

    @tool
    async def extract_job_cards(page_text: str, top_n: int = 10, query_filter: str = "") -> list:
        """从搜索页文本中提取岗位卡片列表。"""
        return await _tools.extract_job_cards_from_page(
            page_text=page_text,
            top_n=top_n,
            query_filter=query_filter,
            api_config=api_config,
        )

    @tool
    async def score_jobs(cards: List[Dict[str, Any]]) -> list:
        """对岗位列表做匹配度打分，按分数降序排列。"""
        return await _tools.score_jobs_by_match(
            cards=cards,
            resume_content=resume_content,
            api_config=api_config,
        )

    @tool
    async def save_job(card_data: Dict[str, Any]) -> Dict[str, Any]:
        """保存单个岗位到数据库。"""
        return await _tools.save_job_to_database(raw_data=card_data, user_id=user_id, platform="boss")

    @tool
    async def generate_assets(job_id: int) -> Dict[str, Any]:
        """为岗位生成投递资产。"""
        return await _tools.generate_job_assets(
            job_id=job_id,
            user_id=user_id,
            resume_content=resume_content,
            api_config=api_config,
        )

    @tool
    async def check_environment() -> str:
        """检测当前环境是否支持自动化。"""
        return await _tools.check_environment()

    return [
        attach_tool_contract(check_environment, effect="read", permissions=("jobs.environment.read",), result_retention="summary"),
        attach_tool_contract(open_boss_search_page, effect="external", permissions=("boss.browser.read",), result_retention="summary"),
        attach_tool_contract(extract_job_cards, effect="read", permissions=("jobs.cards.extract",), result_retention="summary"),
        attach_tool_contract(score_jobs, effect="read", permissions=("jobs.score",), result_retention="summary"),
        attach_tool_contract(
            save_job,
            effect="write",
            permissions=("jobs.capture.write",),
            idempotency_key_strategy="user_id:platform:source_hash",
            result_retention="reference",
        ),
        attach_tool_contract(
            generate_assets,
            effect="write",
            permissions=("jobs.assets.write",),
            idempotency_key_strategy="user_id:job_id:resume_hash",
            result_retention="reference",
        ),
    ]
