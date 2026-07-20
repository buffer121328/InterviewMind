"""项目经历重写用例。"""

from dataclasses import dataclass

from app.infrastructure.db.repositories.resume.project_rewrite_repo import get_project_rewrite_repo
from app.schemas.project_rewrite_schemas import (
    ProjectRewriteDetailResponse,
    ProjectRewriteHistoryItem,
    ProjectRewriteHistoryResponse,
    ProjectRewriteRequest,
    ProjectRewriteResponse,
)
from app.agents.resume.project_rewriter import rewrite_project

VALID_REWRITE_MODES = ["star_rewrite", "quantify_results", "jd_customize", "followup_prediction"]


@dataclass(slots=True)
class ProjectRewriteUseCaseError(Exception):
    """项目经历重写用例异常。"""

    message: str


class ProjectRewriteBadRequest(ProjectRewriteUseCaseError):
    """项目经历重写请求不合法。"""


class ProjectRewriteNotFound(ProjectRewriteUseCaseError):
    """项目经历重写记录不存在或无权访问。"""


class ProjectRewriteUseCases:
    """项目经历重写应用服务。"""

    async def rewrite(self, *, request: ProjectRewriteRequest, user_id: str) -> ProjectRewriteResponse:
        if not request.project_content.strip():
            raise ProjectRewriteBadRequest(message="请输入项目内容")
        if not request.project_title.strip():
            raise ProjectRewriteBadRequest(message="请输入项目标题")
        if not request.api_config:
            raise ProjectRewriteBadRequest(message="请先配置 API Key")
        if request.rewrite_mode not in VALID_REWRITE_MODES:
            raise ProjectRewriteBadRequest(message=f"rewrite_mode 必须是 {VALID_REWRITE_MODES} 之一")

        try:
            result = await rewrite_project(
                project_content=request.project_content,
                project_title=request.project_title,
                rewrite_mode=request.rewrite_mode,
                job_description=request.job_description,
                api_config=request.api_config.model_dump() if request.api_config else None,
            )
        except ValueError as exc:
            raise ProjectRewriteBadRequest(message=str(exc)) from exc

        rewrite_id = await get_project_rewrite_repo().save_rewrite(
            user_id=user_id,
            material_id=request.material_id,
            project_title=request.project_title,
            original_content=request.project_content,
            rewrite_mode=request.rewrite_mode,
            job_description=request.job_description,
            result_data=result,
        )
        return ProjectRewriteResponse(success=True, result=result, rewrite_id=rewrite_id)

    async def list_results(
        self,
        *,
        user_id: str,
        rewrite_mode: str | None,
        limit: int,
    ) -> ProjectRewriteHistoryResponse:
        try:
            records = await get_project_rewrite_repo().list_rewrites(
                user_id=user_id,
                rewrite_mode=rewrite_mode,
                limit=limit,
            )
            return ProjectRewriteHistoryResponse(
                success=True,
                records=[
                    ProjectRewriteHistoryItem(
                        id=row["id"],
                        project_title=row["project_title"],
                        rewrite_mode=row["rewrite_mode"],
                        created_at=row["created_at"],
                    )
                    for row in records
                ],
            )
        except Exception as exc:
            return ProjectRewriteHistoryResponse(success=False, message=str(exc))

    async def get_result(self, *, rewrite_id: int, user_id: str) -> ProjectRewriteDetailResponse:
        record = await get_project_rewrite_repo().get_rewrite(rewrite_id, user_id)
        if not record:
            raise ProjectRewriteNotFound(message="重写记录不存在")
        return ProjectRewriteDetailResponse(success=True, record=record)

    async def delete_result(self, *, rewrite_id: int, user_id: str) -> dict[str, object]:
        success = await get_project_rewrite_repo().delete_rewrite(rewrite_id, user_id)
        if not success:
            raise ProjectRewriteNotFound(message="记录不存在或无权删除")
        return {"success": True, "message": "删除成功"}


project_rewrite_use_cases = ProjectRewriteUseCases()
