"""简历组装用例。"""

from dataclasses import dataclass

from app.services.resume.resume_assembler import (
    assemble_resume_from_materials,
    delete_assembly_result,
    get_assembly_result,
    list_assembly_results,
    save_assembly_result,
    select_materials_for_jd,
)


@dataclass(slots=True)
class ResumeAssemblyUseCaseError(Exception):
    """简历组装用例异常。"""

    message: str


class ResumeAssemblyBadRequest(ResumeAssemblyUseCaseError):
    """简历组装请求不合法。"""


class ResumeAssemblyNotFound(ResumeAssemblyUseCaseError):
    """简历组装结果不存在或无权访问。"""


class ResumeAssemblyUseCases:
    """简历组装应用服务。"""

    async def assemble_resume(self, *, request: dict, user_id: str) -> dict[str, object]:
        job_description = request.get("job_description")
        if not job_description:
            raise ResumeAssemblyBadRequest(message="job_description 为必填字段")
        api_config = request.get("api_config")
        if not api_config:
            raise ResumeAssemblyBadRequest(message="请先配置 API Key")

        try:
            selection_result = await select_materials_for_jd(
                user_id=user_id,
                job_description=job_description,
                api_config=api_config,
                material_type_filter=request.get("material_type_filter"),
                max_materials=request.get("max_materials", 50),
            )
            selected_ids = request.get("selected_material_ids") or selection_result.selected_material_ids
            if not selected_ids:
                return {
                    "success": True,
                    "message": "未找到相关素材，请先添加素材",
                    "selected_material_ids": [],
                    "selection_reason": selection_result.selection_reason,
                    "assembled_outline": selection_result.assembled_outline,
                }

            assembly_result = await assemble_resume_from_materials(
                user_id=user_id,
                job_description=job_description,
                selected_material_ids=selected_ids,
                api_config=api_config,
            )
            result_id = await save_assembly_result(
                user_id=user_id,
                job_description=job_description,
                selected_material_ids=selected_ids,
                selection_reason=selection_result.selection_reason,
                assembled_outline=selection_result.assembled_outline,
                assembled_content=assembly_result["assembled_content"],
            )
            return {
                "success": True,
                "result_id": result_id,
                "selected_material_ids": selected_ids,
                "selection_reason": selection_result.selection_reason,
                "assembled_outline": selection_result.assembled_outline,
                "assembled_content": assembly_result["assembled_content"],
                "materials_used": assembly_result["materials_used"],
            }
        except ValueError as exc:
            raise ResumeAssemblyBadRequest(message=str(exc)) from exc

    async def list_assembly_results(self, *, user_id: str, limit: int) -> dict[str, object]:
        try:
            results = await list_assembly_results(user_id=user_id, limit=limit)
            return {"success": True, "results": results}
        except Exception as exc:
            return {"success": False, "results": [], "message": str(exc)}

    async def get_assembly_result(self, *, result_id: int, user_id: str) -> dict[str, object]:
        result = await get_assembly_result(result_id, user_id)
        if not result:
            raise ResumeAssemblyNotFound(message="组装结果不存在")
        return {"success": True, "result": result}

    async def delete_assembly_result(self, *, result_id: int, user_id: str) -> dict[str, object]:
        success = await delete_assembly_result(result_id, user_id)
        if not success:
            raise ResumeAssemblyNotFound(message="结果不存在或无权删除")
        return {"success": True, "message": "删除成功"}


resume_assembly_use_cases = ResumeAssemblyUseCases()
