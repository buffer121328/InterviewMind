"""
题库 API 路由
提供题库条目的 CRUD、检索、导入功能
"""

import hashlib
import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from app.api.deps import get_current_user_id
from app.application.question_bank import QuestionBankNotFound, question_bank_use_cases
from app.schemas.question_bank import (
    QuestionBankCreateRequest,
    QuestionBankImportRequest,
    QuestionBankImportResponse,
    QuestionBankItem,
    QuestionBankListResponse,
    QuestionFileCandidate,
    QuestionFilePreviewResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/question-bank", tags=["题库"])


@router.post("/import-file/preview", response_model=QuestionFilePreviewResponse)
async def preview_question_file(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
):
    """解析 PDF/Markdown 并返回候选题；此步骤不写入题库。"""
    from app.services.file_service import FileServiceError, file_service
    from app.services.question_bank import parse_question_document

    filename = (file.filename or "questions").strip()[:255]
    try:
        content = await file_service.process_fastapi_file(file)
        source_id = hashlib.sha256(f"{user_id}\0{filename}\0{content}".encode("utf-8")).hexdigest()[:32]
        questions = parse_question_document(content=content, filename=filename, source_id=source_id)
        return QuestionFilePreviewResponse(
            success=True,
            filename=filename,
            questions=[QuestionFileCandidate(**question) for question in questions],
            message=f"解析出 {len(questions)} 道候选题",
        )
    except FileServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/items", response_model=dict)
async def create_question_item(
    request: QuestionBankCreateRequest,
    user_id: str = Depends(get_current_user_id),
):
    """创建题库条目。"""
    try:
        item_id = await question_bank_use_cases.create_item(request=request, user_id=user_id)
        return {"success": True, "item_id": item_id, "message": "创建成功"}
    except Exception as exc:
        logger.error("创建题库条目失败: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/items", response_model=QuestionBankListResponse)
async def list_question_items(
    question_type: Optional[str] = Query(default=None, description="题目类型筛选"),
    difficulty: Optional[str] = Query(default=None, description="难度筛选"),
    is_verified: Optional[bool] = Query(default=None, description="是否已验证"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user_id: str = Depends(get_current_user_id),
):
    """列出题库条目。"""
    try:
        items, total = await question_bank_use_cases.list_items(
            user_id=user_id,
            question_type=question_type,
            difficulty=difficulty,
            is_verified=is_verified,
            limit=limit,
            offset=offset,
        )
        return QuestionBankListResponse(
            success=True,
            items=[QuestionBankItem(**item) for item in items],
            total=total,
        )
    except Exception as exc:
        logger.error("列出题库条目失败: %s", exc)
        return QuestionBankListResponse(success=False, message=str(exc))


@router.get("/items/{item_id}", response_model=dict)
async def get_question_item(
    item_id: int,
    user_id: str = Depends(get_current_user_id),
):
    """获取单个题库条目。"""
    try:
        item = await question_bank_use_cases.get_item(item_id=item_id, user_id=user_id)
        return {"success": True, "item": item}
    except QuestionBankNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("获取题库条目失败: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put("/items/{item_id}", response_model=dict)
async def update_question_item(
    item_id: int,
    request: QuestionBankCreateRequest,
    user_id: str = Depends(get_current_user_id),
):
    """更新题库条目。"""
    try:
        await question_bank_use_cases.update_item(item_id=item_id, request=request, user_id=user_id)
        return {"success": True, "message": "更新成功"}
    except QuestionBankNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("更新题库条目失败: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/items/{item_id}", response_model=dict)
async def delete_question_item(
    item_id: int,
    user_id: str = Depends(get_current_user_id),
):
    """删除题库条目。"""
    try:
        await question_bank_use_cases.delete_item(item_id=item_id, user_id=user_id)
        return {"success": True, "message": "删除成功"}
    except QuestionBankNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("删除题库条目失败: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/search", response_model=QuestionBankListResponse)
async def search_question_items(
    q: str = Query(..., description="搜索关键词"),
    limit: int = Query(default=20, ge=1, le=100),
    user_id: str = Depends(get_current_user_id),
):
    """全文检索题库条目。"""
    try:
        items = await question_bank_use_cases.search_items(user_id=user_id, query=q, limit=limit)
        return QuestionBankListResponse(
            success=True,
            items=[QuestionBankItem(**item) for item in items],
            total=len(items),
        )
    except Exception as exc:
        logger.error("检索题库条目失败: %s", exc)
        return QuestionBankListResponse(success=False, message=str(exc))


@router.post("/import", response_model=QuestionBankImportResponse)
async def import_questions(
    request: QuestionBankImportRequest,
    user_id: str = Depends(get_current_user_id),
):
    """批量导入题目到题库。"""
    try:
        success_count, total_count, import_id = await question_bank_use_cases.import_questions(
            request=request,
            user_id=user_id,
        )
        return QuestionBankImportResponse(
            success=True,
            import_id=import_id,
            total_count=total_count,
            success_count=success_count,
            message=f"成功导入 {success_count}/{total_count} 道题目",
        )
    except Exception as exc:
        logger.error("批量导入题目失败: %s", exc)
        return QuestionBankImportResponse(success=False, message=str(exc))


@router.post("/save-from-session", response_model=dict)
async def save_question_from_session(
    session_id: str = Query(..., description="会话 ID"),
    question_index: int = Query(..., description="题目索引"),
    user_id: str = Depends(get_current_user_id),
):
    """将面试中的题目沉淀到题库。"""
    try:
        item_id = await question_bank_use_cases.save_question_from_session(
            session_id=session_id,
            question_index=question_index,
            user_id=user_id,
        )
        return {"success": True, "item_id": item_id, "message": "题目已沉淀到题库"}
    except QuestionBankNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("沉淀题目失败: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
