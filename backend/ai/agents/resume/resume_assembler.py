"""
简历组装核心逻辑
根据 JD 自动筛选素材并组装简历
"""

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage
from sqlalchemy import delete, select

from ai.llm import llms
from ai.prompts.resume import (
    build_assembler_assemble_prompt,
    build_assembler_system_prompt,
    build_assembler_user_prompt,
)
from ai.runtime.context.assembler import ContextAssembler, ContextSource
from ai.runtime.execution.deadlines import TaskDeadline, get_current_task_deadline
from app.config import get_settings
from app.db.models import async_session
from app.db.models.resume import ResumeAssemblyResultModel
from app.db.repositories.resume.candidate_material_repo import (
    get_candidate_material_repo,
)

logger = logging.getLogger(__name__)


# ============================================================================
# LLM 输出结构
# ============================================================================

# 素材筛选结果结构
class MaterialSelectionResult:
    """素材筛选结果"""
    def __init__(
        self,
        selected_material_ids: List[int],
        selection_reason: str,
        assembled_outline: Dict[str, Any]
    ):
        """初始化 `MaterialSelectionResult` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端仅在后续方法调用时承担对应的访问边界。

        Args:
            selected_material_ids: selected material 标识列表。
            selection_reason: 经过类型边界校验的 `selection_reason`；其格式和可选值由参数类型及调用流程约束。
            assembled_outline: 经过类型边界校验的 `assembled_outline`；其格式和可选值由参数类型及调用流程约束。
        """
        self.selected_material_ids = selected_material_ids
        self.selection_reason = selection_reason
        self.assembled_outline = assembled_outline


# ============================================================================
# 提示词兼容封装
# ============================================================================

SYSTEM_PROMPT = build_assembler_system_prompt()


def _material_tokens(value: str) -> set[str]:
    """处理材料令牌相关后端逻辑。"""
    lowered = str(value or "").casefold()
    tokens = set(re.findall(r"[a-z][a-z0-9.+#_-]{1,}|\d+(?:\.\d+)?", lowered))
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", lowered):
        tokens.update(chunk[index:index + 2] for index in range(len(chunk) - 1))
    return tokens


def rank_materials_for_jd(
    job_description: str,
    materials: List[Dict[str, Any]],
    *,
    limit: int | None = None,
    item_max_chars: int | None = None,
) -> List[Dict[str, Any]]:
    """处理排序材料JD相关后端逻辑。"""
    settings = get_settings()
    top_k = min(limit or settings.resume_material_max_items, settings.resume_material_max_items)
    max_chars = item_max_chars or settings.resume_material_item_max_chars
    jd_tokens = _material_tokens(job_description)
    ranked: list[tuple[float, int, Dict[str, Any]]] = []
    for material in materials:
        content = str(material.get("content") or "").strip()
        if not content:
            continue
        tags = material.get("tags") or []
        searchable = " ".join([
            str(material.get("material_type") or ""),
            str(material.get("title") or ""),
            " ".join(str(tag) for tag in tags),
            content,
        ])
        overlap = len(jd_tokens & _material_tokens(searchable))
        importance = max(0.0, min(1.0, float(material.get("importance_score") or 0.0)))
        confidence = max(0.0, min(1.0, float(material.get("confidence_score") or 0.0)))
        verified = 1.0 if material.get("is_verified") else 0.0
        score = overlap * 2.0 + importance + confidence + verified
        clipped = dict(material)
        clipped["content"] = content[:max_chars]
        clipped["tags"] = list(tags)[:12]
        ranked.append((score, int(material.get("id") or 0), clipped))
    ranked.sort(key=lambda item: (-item[0], -int(bool(item[2].get("is_verified"))), item[1]))
    return [item[2] for item in ranked[:top_k]]


def _assemble_material_context(
    *,
    stage: str,
    job_description: str,
    materials: List[Dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    """组装材料上下文相关后端逻辑。"""
    settings = get_settings()
    material_budget = settings.resume_material_max_items * settings.resume_material_item_max_chars
    assembled = ContextAssembler(
        agent_name="resume_generator",
        total_model_chars=3500 + material_budget,
        source_budgets={"job_description": 3500, "materials": material_budget},
    ).assemble([
        ContextSource(
            name="job_description",
            content=job_description,
            trusted=False,
            required=True,
            priority=100,
            max_chars=3500,
            truncation_strategy="head_tail",
        ),
        ContextSource(
            name="materials",
            content=materials,
            trusted=True,
            required=True,
            priority=90,
            max_chars=material_budget,
            truncation_strategy="head_tail",
        ),
    ])
    return assembled.model_context, {**assembled.model_event_fields(), "stage": stage}


def build_user_prompt(job_description: str, materials: List[Dict[str, Any]]) -> str:
    """构建用户提示词相关后端逻辑。"""
    materials_text = []
    for material in materials:
        materials_text.append(
            "\n".join([
                f"素材 ID: {material['id']}",
                f"类型: {material['material_type']}",
                f"标题: {material['title']}",
                f"内容: {str(material['content'])[:get_settings().resume_material_item_max_chars]}",
                f"标签: {', '.join(material['tags']) if material['tags'] else '无'}",
                f"重要性: {material['importance_score']}",
                f"可信度: {material['confidence_score']}",
                f"已验证: {'是' if material['is_verified'] else '否'}",
            ])
        )
    return f"{SYSTEM_PROMPT}\n\n" + build_assembler_user_prompt(
        job_description=job_description,
        materials_str="\n---\n".join(materials_text),
    )


# ============================================================================
# 核心组装函数
# ============================================================================

async def select_materials_for_jd(
    user_id: str,
    job_description: str,
    api_config: Optional[dict] = None,
    material_type_filter: Optional[str] = None,
    max_materials: int = 50,
    deadline: TaskDeadline | None = None,
) -> MaterialSelectionResult:
    """
    根据 JD 筛选素材

    Args:
        user_id: 用户ID
        job_description: 目标职位描述
        api_config: API 配置
        material_type_filter: 素材类型过滤（可选）
        max_materials: 最大素材数量
        deadline: 与后续组装复用的任务总 deadline。

    Returns:
        素材筛选结果
    """
    # 获取素材服务
    material_service = get_candidate_material_repo()

    # 获取用户的素材列表
    materials = await material_service.list_materials(
        user_id=user_id,
        material_type=material_type_filter,
        limit=max_materials
    )

    if not materials:
        logger.warning(f"用户 {user_id} 没有素材")
        return MaterialSelectionResult(
            selected_material_ids=[],
            selection_reason="素材库为空，请先添加素材",
            assembled_outline={}
        )

    ranked_materials = rank_materials_for_jd(
        job_description,
        materials,
        limit=max_materials,
    )
    context_text, call_metadata = _assemble_material_context(
        stage="resume_material_selection",
        job_description=job_description,
        materials=ranked_materials,
    )
    messages = [HumanMessage(content=f"{SYSTEM_PROMPT}\n\n{context_text}")]

    # 调用 LLM
    logger.info("开始素材筛选: user=%s, candidate_count=%s", user_id, len(ranked_materials))
    deadline = deadline or get_current_task_deadline()
    try:
        response = await llms.invoke_text(
            messages,
            api_config,
            channel="smart",
            deadline=deadline,
            call_metadata=call_metadata,
        )
    except Exception as exc:
        logger.warning("素材筛选模型不可用，使用本地 Top-K: %s", type(exc).__name__)
        return MaterialSelectionResult(
            selected_material_ids=[int(item["id"]) for item in ranked_materials],
            selection_reason="模型筛选不可用，已按 JD 相关度、可信度和重要性使用本地 Top-K",
            assembled_outline={},
        )

    # 解析响应
    try:
        result_text = response.content.strip()
        # 尝试提取 JSON（处理可能的 markdown 代码块）
        if result_text.startswith("```"):
            # 移除 markdown 代码块标记
            lines = result_text.split("\n")
            json_lines = []
            in_block = False
            for line in lines:
                if line.startswith("```") and not in_block:
                    in_block = True
                    continue
                elif line.startswith("```") and in_block:
                    break
                elif in_block:
                    json_lines.append(line)
            result_text = "\n".join(json_lines)

        result = json.loads(result_text)
    except json.JSONDecodeError as e:
        logger.warning("素材筛选输出格式异常，使用本地 Top-K: %s", type(e).__name__)
        return MaterialSelectionResult(
            selected_material_ids=[int(item["id"]) for item in ranked_materials],
            selection_reason="模型输出格式异常，已按 JD 相关度、可信度和重要性使用本地 Top-K",
            assembled_outline={},
        )

    # 验证选中的素材 ID 是否有效
    valid_material_ids = {m['id'] for m in ranked_materials}
    selected_ids = [
        mid for mid in result.get("selected_material_ids", [])
        if mid in valid_material_ids
    ]

    if not selected_ids:
        selected_ids = [int(item["id"]) for item in ranked_materials]
    logger.info("素材筛选完成: selected=%s, candidates=%s", len(selected_ids), len(ranked_materials))

    return MaterialSelectionResult(
        selected_material_ids=selected_ids,
        selection_reason=result.get("selection_reason", ""),
        assembled_outline=result.get("assembled_outline", {})
    )


async def assemble_resume_from_materials(
    user_id: str,
    job_description: str,
    selected_material_ids: List[int],
    api_config: Optional[dict] = None,
    deadline: TaskDeadline | None = None,
) -> Dict[str, Any]:
    """
    根据选中的素材组装简历

    Args:
        user_id: 用户ID
        job_description: 目标职位描述
        selected_material_ids: 选中的素材 ID 列表
        api_config: API 配置
        deadline: 与素材筛选复用的任务总 deadline。

    Returns:
        组装结果，包含 assembled_content
    """
    # 获取素材服务
    material_service = get_candidate_material_repo()

    # 获取选中的素材
    materials = await material_service.get_materials_by_ids(
        material_ids=selected_material_ids,
        user_id=user_id
    )

    if not materials:
        raise ValueError("未找到选中的素材")

    materials = rank_materials_for_jd(job_description, materials)
    if not materials:
        raise ValueError("选中的素材为空或不包含有效内容")
    context_text, call_metadata = _assemble_material_context(
        stage="resume_material_assembly",
        job_description=job_description,
        materials=materials,
    )

    prompt = build_assembler_assemble_prompt(
        job_description="",
        materials_str=context_text,
    )

    # 调用 LLM
    logger.info(f"开始组装简历: user={user_id}, materials_count={len(materials)}")
    messages = [HumanMessage(content=prompt)]
    response = await llms.invoke_text(
        messages,
        api_config,
        channel="smart",
        deadline=deadline or get_current_task_deadline(),
        call_metadata=call_metadata,
    )

    assembled_content = response.content.strip()

    logger.info(f"简历组装完成: content_length={len(assembled_content)}")

    return {
        "assembled_content": assembled_content,
        "selected_material_ids": [int(material["id"]) for material in materials],
        "materials_used": [
            {
                "id": m['id'],
                "type": m['material_type'],
                "title": m['title']
            }
            for m in materials
        ]
    }


async def save_assembly_result(
    user_id: str,
    job_description: str,
    selected_material_ids: List[int],
    selection_reason: str,
    assembled_outline: Dict[str, Any],
    assembled_content: Optional[str] = None,
    generated_resume_id: Optional[int] = None
) -> int:
    """
    保存组装结果

    Args:
        user_id: 用户ID
        job_description: 目标职位描述
        selected_material_ids: 选中的素材 ID 列表
        selection_reason: 筛选理由
        assembled_outline: 组装大纲
        assembled_content: 组装后的内容
        generated_resume_id: 生成的简历 ID

    Returns:
        组装结果 ID
    """
    async with async_session() as db:
        try:
            db_obj = ResumeAssemblyResultModel(
                user_id=user_id,
                job_description=job_description,
                selected_material_ids=selected_material_ids,
                selection_reason=selection_reason,
                assembled_outline=assembled_outline,
                assembled_content=assembled_content,
                generated_resume_id=generated_resume_id,
                created_at=datetime.now(),
            )
            db.add(db_obj)
            await db.commit()
            await db.refresh(db_obj)
            result_id = db_obj.id

            logger.info(f"保存组装结果: ID={result_id}, user={user_id}")
            return result_id

        except Exception as e:
            logger.error("保存组装结果失败: %s", type(e).__name__)
            raise


async def get_assembly_result(
    result_id: int,
    user_id: str
) -> Optional[Dict[str, Any]]:
    """
    获取组装结果

    Args:
        result_id: 结果ID
        user_id: 用户ID

    Returns:
        组装结果数据
    """
    async with async_session() as db:
        stmt = select(ResumeAssemblyResultModel).where(
            ResumeAssemblyResultModel.id == result_id,
            ResumeAssemblyResultModel.user_id == user_id
        )
        result = await db.execute(stmt)
        obj = result.scalar_one_or_none()

        if not obj:
            return None

        return {
            'id': obj.id,
            'user_id': obj.user_id,
            'job_description': obj.job_description,
            'selected_material_ids': obj.selected_material_ids,
            'selection_reason': obj.selection_reason,
            'assembled_outline': obj.assembled_outline if obj.assembled_outline else {},
            'assembled_content': obj.assembled_content,
            'generated_resume_id': obj.generated_resume_id,
            'created_at': obj.created_at.isoformat() if hasattr(obj.created_at, 'isoformat') else obj.created_at
        }


async def list_assembly_results(
    user_id: str,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """
    获取用户的组装结果列表

    Args:
        user_id: 用户ID
        limit: 最大返回数量

    Returns:
        组装结果列表
    """
    async with async_session() as db:
        stmt = select(ResumeAssemblyResultModel).where(
            ResumeAssemblyResultModel.user_id == user_id
        ).order_by(ResumeAssemblyResultModel.created_at.desc()).limit(limit)
        result = await db.execute(stmt)
        rows = result.scalars().all()

        return [
            {
                'id': obj.id,
                'user_id': obj.user_id,
                'job_description': obj.job_description[:200] if obj.job_description else '',
                'selected_material_ids': obj.selected_material_ids,
                'selection_reason': obj.selection_reason,
                'assembled_outline': obj.assembled_outline if obj.assembled_outline else {},
                'assembled_content': obj.assembled_content,
                'generated_resume_id': obj.generated_resume_id,
                'created_at': obj.created_at.isoformat() if hasattr(obj.created_at, 'isoformat') else obj.created_at
            }
            for obj in rows
        ]


async def delete_assembly_result(
    result_id: int,
    user_id: str
) -> bool:
    """
    删除组装结果

    Args:
        result_id: 结果ID
        user_id: 用户ID

    Returns:
        是否删除成功
    """
    async with async_session() as db:
        try:
            result = await db.execute(
                delete(ResumeAssemblyResultModel).where(
                    ResumeAssemblyResultModel.id == result_id,
                    ResumeAssemblyResultModel.user_id == user_id
                )
            )
            await db.commit()

            deleted = result.rowcount > 0
            if deleted:
                logger.info(f"删除组装结果: ID={result_id}")
            return deleted

        except Exception as e:
            logger.error("删除组装结果失败: %s", type(e).__name__)
            return False
