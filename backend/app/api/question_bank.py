"""
题库 API 路由
提供题库条目的 CRUD、检索、导入功能
"""

import hashlib
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends, File, UploadFile

from app.schemas.question_bank import (
    QuestionBankItem,
    QuestionBankCreateRequest,
    QuestionBankListResponse,
    QuestionBankImportRequest,
    QuestionBankImportResponse,
    QuestionFileCandidate,
    QuestionFilePreviewResponse,
)
from app.repositories.interview.question_bank_repo import get_question_bank_repo
from app.api.deps import get_current_user_id

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
    user_id: str = Depends(get_current_user_id)
):
    """创建题库条目"""
    try:
        service = get_question_bank_repo()
        item_id = await service.create_item(
            user_id=user_id,
            question_text=request.question_text,
            reference_answer=request.reference_answer,
            tags=request.tags,
            difficulty=request.difficulty,
            target_skill=request.target_skill,
            question_type=request.question_type,
            source_type=request.source_type
        )
        return {"success": True, "item_id": item_id, "message": "创建成功"}
    except Exception as e:
        logger.error(f"创建题库条目失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/items", response_model=QuestionBankListResponse)
async def list_question_items(
    question_type: Optional[str] = Query(default=None, description="题目类型筛选"),
    difficulty: Optional[str] = Query(default=None, description="难度筛选"),
    is_verified: Optional[bool] = Query(default=None, description="是否已验证"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user_id: str = Depends(get_current_user_id)
):
    """列出题库条目"""
    try:
        service = get_question_bank_repo()
        items = await service.list_items(
            user_id=user_id,
            question_type=question_type,
            difficulty=difficulty,
            is_verified=is_verified,
            limit=limit,
            offset=offset
        )
        return QuestionBankListResponse(
            success=True,
            items=[QuestionBankItem(**item) for item in items],
            total=len(items)
        )
    except Exception as e:
        logger.error(f"列出题库条目失败: {e}")
        return QuestionBankListResponse(success=False, message=str(e))


@router.get("/items/{item_id}", response_model=dict)
async def get_question_item(
    item_id: int,
    user_id: str = Depends(get_current_user_id)
):
    """获取单个题库条目"""
    try:
        service = get_question_bank_repo()
        item = await service.get_item(item_id, user_id)
        if not item:
            raise HTTPException(status_code=404, detail="条目不存在")
        return {"success": True, "item": item}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取题库条目失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/items/{item_id}", response_model=dict)
async def update_question_item(
    item_id: int,
    request: QuestionBankCreateRequest,
    user_id: str = Depends(get_current_user_id)
):
    """更新题库条目"""
    try:
        service = get_question_bank_repo()
        updated = await service.update_item(
            item_id=item_id,
            user_id=user_id,
            question_text=request.question_text,
            reference_answer=request.reference_answer,
            tags=request.tags,
            difficulty=request.difficulty,
            target_skill=request.target_skill,
            question_type=request.question_type
        )
        if not updated:
            raise HTTPException(status_code=404, detail="条目不存在或无权更新")
        return {"success": True, "message": "更新成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新题库条目失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/items/{item_id}", response_model=dict)
async def delete_question_item(
    item_id: int,
    user_id: str = Depends(get_current_user_id)
):
    """删除题库条目"""
    try:
        service = get_question_bank_repo()
        deleted = await service.delete_item(item_id, user_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="条目不存在或无权删除")
        return {"success": True, "message": "删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除题库条目失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search", response_model=QuestionBankListResponse)
async def search_question_items(
    q: str = Query(..., description="搜索关键词"),
    limit: int = Query(default=20, ge=1, le=100),
    user_id: str = Depends(get_current_user_id)
):
    """全文检索题库条目"""
    try:
        service = get_question_bank_repo()
        items = await service.search_items(user_id=user_id, query=q, limit=limit)
        return QuestionBankListResponse(
            success=True,
            items=[QuestionBankItem(**item) for item in items],
            total=len(items)
        )
    except Exception as e:
        logger.error(f"检索题库条目失败: {e}")
        return QuestionBankListResponse(success=False, message=str(e))


@router.post("/import", response_model=QuestionBankImportResponse)
async def import_questions(
    request: QuestionBankImportRequest,
    user_id: str = Depends(get_current_user_id)
):
    """批量导入题目到题库"""
    try:
        service = get_question_bank_repo()
        success_count = 0
        total_count = len(request.questions)

        for q in request.questions:
            try:
                await service.create_item(
                    user_id=user_id,
                    question_text=q.get("question_text", q.get("content", "")),
                    reference_answer=q.get("reference_answer"),
                    tags=q.get("tags", []),
                    difficulty=q.get("difficulty", "medium"),
                    target_skill=q.get("target_skill"),
                    question_type=q.get("question_type", "tech"),
                    source_type=q.get("source_type", request.import_source),
                    source_id=q.get("source_id"),
                )
                success_count += 1
            except Exception as e:
                logger.warning(f"导入单条题目失败: {e}")

        import_id = await service.save_import_record(
            user_id=user_id,
            import_source=request.import_source,
            file_name=None,
            total_count=total_count,
            success_count=success_count,
            summary=f"成功导入 {success_count}/{total_count} 道题目"
        )

        return QuestionBankImportResponse(
            success=True,
            import_id=import_id,
            total_count=total_count,
            success_count=success_count,
            message=f"成功导入 {success_count}/{total_count} 道题目"
        )
    except Exception as e:
        logger.error(f"批量导入题目失败: {e}")
        return QuestionBankImportResponse(success=False, message=str(e))


@router.post("/save-from-session", response_model=dict)
async def save_question_from_session(
    session_id: str = Query(..., description="会话 ID"),
    question_index: int = Query(..., description="题目索引"),
    user_id: str = Depends(get_current_user_id)
):
    """将面试中的题目沉淀到题库"""
    try:
        from app.repositories.session.session_repo import SessionRepo

        session_repo = SessionRepo()
        session = await session_repo.get_session(session_id, user_id=user_id)

        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")

        plan = await session_repo.get_interview_plan(session_id)
        if not plan or question_index < 0 or question_index >= len(plan):
            raise HTTPException(status_code=404, detail="题目不存在")

        question = plan[question_index]

        service = get_question_bank_repo()
        item_id = await service.create_item(
            user_id=user_id,
            question_text=question.get("content", ""),
            reference_answer=question.get("hint"),
            tags=[question.get("topic", "")],
            difficulty="medium",
            target_skill=question.get("topic"),
            question_type=question.get("type", "tech"),
            source_type="generated",
            source_id=session_id,
            origin_session_id=session_id
        )

        return {"success": True, "item_id": item_id, "message": "题目已沉淀到题库"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"沉淀题目失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
