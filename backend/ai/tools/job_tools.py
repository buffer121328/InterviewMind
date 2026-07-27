"""
岗位相关工具工厂
"""

from typing import Any, Dict, List, Optional

from langchain_core.tools import tool

from app.schemas.tools import attach_tool_contract

from ai.tools import boss_tools as _tools


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

    def attach(contract_name: str, tool: Any) -> Any:
        """把岗位工具的领域契约附加到 LangChain 工具，确保权限、确认、幂等和结果保留策略不被工厂调用方绕过。"""
        contract = _tools.get_boss_tool_contract(contract_name)
        return attach_tool_contract(
            tool,
            effect=contract.effect,
            permissions=contract.permissions,
            requires_confirmation=contract.requires_confirmation,
            idempotency_key_strategy=contract.idempotency_key_strategy,
            result_retention=contract.result_retention,
        )

    return [
        attach("check_environment", check_environment),
        attach("open_boss_search_page", open_boss_search_page),
        attach("extract_job_cards_from_page", extract_job_cards),
        attach("score_jobs_by_match", score_jobs),
        attach("save_job_to_database", save_job),
        attach("generate_job_assets", generate_assets),
    ]
