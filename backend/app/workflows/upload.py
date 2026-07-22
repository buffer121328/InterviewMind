"""Upload processing use cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.infrastructure.files.file_service import (
    FileService,
    FileServiceError,
    FileSizeExceededError,
    UnsupportedFileTypeError,
)
from app.schemas.schemas import FileUploadResponse


@dataclass(slots=True)
class UploadUseCaseError(Exception):
    """Upload processing failure with HTTP-neutral error details."""

    status_code: int
    detail: dict[str, Any]


class UploadUseCases:
    """Process uploaded files outside API route handlers."""

    def __init__(self) -> None:
        self._file_service = FileService()

    async def upload_resume(self, file: Any) -> FileUploadResponse:
        """Extract text from an uploaded resume file."""
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
