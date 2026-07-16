"""
简历组装核心逻辑
根据 JD 自动筛选素材并组装简历
"""

import json
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime

from langchain_core.messages import HumanMessage
from sqlalchemy import delete, select

from app.models import async_session
from app.models.resume import ResumeAssemblyResultModel
from app.services import llms
from app.repositories.resume.candidate_material_repo import get_candidate_material_repo

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
        self.selected_material_ids = selected_material_ids
        self.selection_reason = selection_reason
        self.assembled_outline = assembled_outline


# ============================================================================
# Prompt 模板
# ============================================================================

SYSTEM_PROMPT = """你是一位资深的简历策划师。你的任务是根据目标岗位 JD，从候选人的素材库中筛选最相关的素材，并规划简历结构。

工作流程：
1. 分析 JD 的核心需求（技能、经验、项目类型）
2. 从素材库中筛选与 JD 高度相关的素材
3. 规划简历结构，确定每个部分使用哪些素材
4. 输出筛选理由和简历大纲

筛选原则：
- 优先选择与 JD 关键词匹配度高的素材
- 优先选择已验证（is_verified=true）的素材
- 考虑素材的重要性评分（importance_score）和可信度评分（confidence_score）
- 保持多样性，覆盖 JD 的不同维度
- 如果素材库中没有合适的内容，明确指出

输出要求：
- selected_material_ids: 选中的素材 ID 列表
- selection_reason: 详细说明为什么选择这些素材，每个素材被选中的原因
- assembled_outline: 简历大纲，包含各部分标题和对应的素材 ID

请严格以 JSON 格式输出，不要包含任何其他文本。"""


def build_user_prompt(
    job_description: str,
    materials: List[Dict[str, Any]]
) -> str:
    """构建用户 prompt"""
    
    # 格式化素材列表
    materials_text = []
    for m in materials:
        material_info = f"""素材 ID: {m['id']}
类型: {m['material_type']}
标题: {m['title']}
内容: {m['content'][:500]}{'...' if len(m['content']) > 500 else ''}
标签: {', '.join(m['tags']) if m['tags'] else '无'}
重要性: {m['importance_score']}
可信度: {m['confidence_score']}
已验证: {'是' if m['is_verified'] else '否'}"""
        materials_text.append(material_info)
    
    materials_str = "\n---\n".join(materials_text)
    
    return f"""请根据以下 JD 从素材库中筛选最相关的素材，并规划简历结构。

## 目标岗位 JD
{job_description}

## 候选人素材库
{materials_str}

请按照要求的 JSON 格式输出筛选结果。"""


# ============================================================================
# 核心组装函数
# ============================================================================

async def select_materials_for_jd(
    user_id: str,
    job_description: str,
    api_config: Optional[dict] = None,
    material_type_filter: Optional[str] = None,
    max_materials: int = 50
) -> MaterialSelectionResult:
    """
    根据 JD 筛选素材
    
    Args:
        user_id: 用户ID
        job_description: 目标职位描述
        api_config: API 配置
        material_type_filter: 素材类型过滤（可选）
        max_materials: 最大素材数量
        
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
    
    # 构建消息
    messages = [
        HumanMessage(content=build_user_prompt(job_description, materials))
    ]
    
    # 调用 LLM
    logger.info(f"开始素材筛选: user={user_id}, materials_count={len(materials)}")
    response = await llms.invoke_text(messages, api_config, channel="smart")
    
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
        logger.error(f"LLM 输出 JSON 解析失败: {e}\n原始输出: {response.content}")
        raise ValueError(f"AI 筛选结果格式异常，请重试。错误详情: {str(e)}")
    
    # 验证选中的素材 ID 是否有效
    valid_material_ids = {m['id'] for m in materials}
    selected_ids = [
        mid for mid in result.get("selected_material_ids", [])
        if mid in valid_material_ids
    ]
    
    logger.info(f"素材筛选完成: selected={len(selected_ids)}, total={len(materials)}")
    
    return MaterialSelectionResult(
        selected_material_ids=selected_ids,
        selection_reason=result.get("selection_reason", ""),
        assembled_outline=result.get("assembled_outline", {})
    )


async def assemble_resume_from_materials(
    user_id: str,
    job_description: str,
    selected_material_ids: List[int],
    api_config: Optional[dict] = None
) -> Dict[str, Any]:
    """
    根据选中的素材组装简历
    
    Args:
        user_id: 用户ID
        job_description: 目标职位描述
        selected_material_ids: 选中的素材 ID 列表
        api_config: API 配置
        
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
    
    # 构建组装 prompt
    materials_text = []
    for m in materials:
        material_info = f"""【{m['material_type']}】{m['title']}
{m['content']}"""
        materials_text.append(material_info)
    
    materials_str = "\n\n".join(materials_text)
    
    prompt = f"""请根据以下素材和目标岗位 JD，生成一份专业的简历内容。

## 目标岗位 JD
{job_description}

## 候选人素材
{materials_str}

## 要求
1. 使用 Markdown 格式
2. 突出与 JD 相关的经验和技能
3. 保持真实性，不要编造不存在的经历
4. 语言简洁专业
5. 包含以下部分（根据素材情况调整）：
   - 个人信息
   - 教育背景
   - 工作/实习经历
   - 项目经历
   - 技能特长
   - 其他亮点

请直接输出简历内容，不要包含其他说明。"""
    
    # 调用 LLM
    logger.info(f"开始组装简历: user={user_id}, materials_count={len(materials)}")
    messages = [HumanMessage(content=prompt)]
    response = await llms.invoke_text(messages, api_config, channel="smart")
    
    assembled_content = response.content.strip()
    
    logger.info(f"简历组装完成: content_length={len(assembled_content)}")
    
    return {
        "assembled_content": assembled_content,
        "selected_material_ids": selected_material_ids,
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
            logger.error(f"保存组装结果失败: {e}")
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
            logger.error(f"删除组装结果失败: {e}")
            return False
