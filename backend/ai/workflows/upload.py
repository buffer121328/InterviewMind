"""提供后端逻辑相关后端功能。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.files.file_service import (
    FileService,
    FileServiceError,
    FileSizeExceededError,
    UnsupportedFileTypeError,
)
from app.schemas.schemas import FileUploadResponse


@dataclass(slots=True)
class UploadUseCaseError(Exception):
    """定义用例案例错误相关后端数据结构或服务组件。"""

    status_code: int
    detail: dict[str, Any]


class UploadUseCases:
    """定义用例案例相关后端数据结构或服务组件。"""

    def __init__(self) -> None:
        """初始化上传用例使用的文件服务；文件类型、大小和解析边界由 FileService 统一执行。"""
        self._file_service = FileService()

    async def upload_resume(self, file: Any) -> FileUploadResponse:
        """上传简历相关后端逻辑。"""
        try:
            text_content = await self._file_service.process_fastapi_file(file)
        except UnsupportedFileTypeError as exc:
            raise UploadUseCaseError(
                status_code=400,
                detail={
                    "error": "UnsupportedFileType",
                    "message": str(exc),
                    "supported_formats": self._file_service.allowed_extensions,
                },
            ) from exc
        except FileSizeExceededError as exc:
            raise UploadUseCaseError(
                status_code=413,
                detail={
                    "error": "FileSizeExceeded",
                    "message": str(exc),
                    "max_size_mb": self._file_service.max_file_size_bytes / (1024 * 1024),
                },
            ) from exc
        except FileServiceError as exc:
            raise UploadUseCaseError(
                status_code=400,
                detail={"error": "FileServiceError", "message": str(exc)},
            ) from exc

        return FileUploadResponse(
            success=True,
            message=f"文件 {file.filename} 处理成功",
            filename=file.filename,
            content_length=len(text_content),
            text_content=text_content,
        )


upload_use_cases = UploadUseCases()
