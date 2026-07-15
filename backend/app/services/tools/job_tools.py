"""
岗位相关工具工厂
"""

from typing import Any, Dict, List, Optional

from langchain_core.tools import tool

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

    return [check_environment, open_boss_search_page, extract_job_cards, score_jobs, save_job, generate_assets]
