"""JD 匹配分析用例。"""

from dataclasses import dataclass

from app.application.unit_of_work import UnitOfWork
from app.models import async_session
from app.repositories.resume.jd_analysis_repo import get_jd_analysis_repo
from app.schemas.jd_schemas import (
    JDMatchDetailResponse,
    JDMatchHistoryItem,
    JDMatchHistoryResponse,
    JDMatchRequest,
    JDMatchResponse,
)
from app.services.resume.jd_matcher import analyze_jd_match


@dataclass(slots=True)
class JDMatchUseCaseError(Exception):
    """JD 匹配用例异常。"""

    message: str


class JDMatchBadRequest(JDMatchUseCaseError):
    """JD 匹配请求不合法。"""


class JDMatchNotFound(JDMatchUseCaseError):
    """JD 匹配结果不存在或无权访问。"""


class JDMatchUseCases:
    """JD 匹配分析应用服务。"""

    async def analyze(self, *, request: JDMatchRequest, user_id: str) -> JDMatchResponse:
        if not request.resume_content.strip():
            raise JDMatchBadRequest(message="请输入简历内容")
        if not request.job_description.strip():
            raise JDMatchBadRequest(message="请输入目标职位描述")
        if not request.api_config:
            raise JDMatchBadRequest(message="请先配置 API Key")

        try:
            result = await analyze_jd_match(
                resume_content=request.resume_content,
                job_description=request.job_description,
                api_config=request.api_config.model_dump() if request.api_config else None,
            )
        except ValueError as exc:
            raise JDMatchBadRequest(message=str(exc)) from exc

        async with UnitOfWork(async_session) as uow:
            analysis_id = await get_jd_analysis_repo().save_result(
                user_id=user_id,
                resume_source_type=request.resume_source_type,
                resume_content_snapshot=request.resume_content,
                job_description=request.job_description,
                analysis_result=result,
                resume_source_id=request.resume_source_id,
                session=uow.db,
            )
        return JDMatchResponse(success=True, result=result, analysis_id=analysis_id)

    async def list_results(self, *, user_id: str, limit: int) -> JDMatchHistoryResponse:
        try:
            results = await get_jd_analysis_repo().list_results(user_id=user_id, limit=limit)
            return JDMatchHistoryResponse(
                success=True,
                results=[
                    JDMatchHistoryItem(
                        id=row["id"],
                        resume_source_type=row["resume_source_type"],
                        resume_source_id=row.get("resume_source_id"),
                        job_description=row["job_description"][:200] if row.get("job_description") else "",
                        created_at=row["created_at"],
                    )
                    for row in results
                ],
            )
        except Exception as exc:
            return JDMatchHistoryResponse(success=False, message=str(exc))

    async def get_result(self, *, analysis_id: int, user_id: str) -> JDMatchDetailResponse:
        result = await get_jd_analysis_repo().get_result(analysis_id, user_id)
        if not result:
            raise JDMatchNotFound(message="分析结果不存在")
        return JDMatchDetailResponse(success=True, result=result)

    async def delete_result(self, *, analysis_id: int, user_id: str) -> dict[str, object]:
        success = await get_jd_analysis_repo().delete_result(analysis_id, user_id)
        if not success:
            raise JDMatchNotFound(message="结果不存在或无权删除")
        return {"success": True, "message": "删除成功"}


jd_match_use_cases = JDMatchUseCases()
