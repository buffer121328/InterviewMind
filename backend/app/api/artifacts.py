"""提供产物相关后端功能。"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.api.deps import get_current_user_id
from app.files.artifact_service import ArtifactNotFound, ArtifactService, ArtifactStorageUnavailable
from app.schemas.artifacts import ArtifactExportRequest, ArtifactResponse

router = APIRouter(prefix="/api/artifacts", tags=["Artifacts"])
_service = ArtifactService()


def _response(artifact) -> ArtifactResponse:
    """处理响应相关后端逻辑。"""
    return ArtifactResponse(
        id=artifact.id,
        source_type=artifact.source_type,
        source_id=artifact.source_id,
        title=artifact.title,
        format=artifact.format,
        mime_type=artifact.mime_type,
        size_bytes=artifact.size_bytes,
        created_at=artifact.created_at.isoformat(),
        download_url=f"/api/artifacts/{artifact.id}/download",
        artifact_mode=artifact.artifact_mode,
        report_source_version=artifact.report_source_version,
    )


@router.post("/export", response_model=ArtifactResponse, status_code=201)
async def export_artifact(request: ArtifactExportRequest, user_id: str = Depends(get_current_user_id)) -> ArtifactResponse:
    """处理产物相关后端逻辑。"""
    try:
        return _response(await _service.export(request, user_id))
    except (ArtifactNotFound, ValueError) as exc:
        raise HTTPException(status_code=404, detail="报告不存在或无权导出") from exc
    except ArtifactStorageUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail="导出存储暂不可用，请稍后重试",
        ) from exc


@router.get("/{artifact_id}/download")
async def download_artifact(artifact_id: int, user_id: str = Depends(get_current_user_id)) -> FileResponse:
    """下载产物相关后端逻辑。"""
    try:
        artifact, path = await _service.get_download(artifact_id, user_id)
    except ArtifactNotFound as exc:
        raise HTTPException(status_code=404, detail="文件不存在或无权访问") from exc
    return FileResponse(path, media_type=artifact.mime_type, filename=path.name)
