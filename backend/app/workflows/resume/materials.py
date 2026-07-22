"""候选人素材库用例。"""

import json
from dataclasses import dataclass

from langchain_core.messages import HumanMessage

from app.infrastructure.db.repositories.resume.candidate_material_repo import get_candidate_material_repo
from app.infrastructure.llm import llms

VALID_MATERIAL_TYPES = [
    "tech_stack",
    "project",
    "internship",
    "work_experience",
    "education",
    "certificate",
    "highlight",
]


@dataclass(slots=True)
class ResumeMaterialUseCaseError(Exception):
    """候选人素材用例异常。"""

    message: str


class ResumeMaterialBadRequest(ResumeMaterialUseCaseError):
    """素材请求参数不完整或不合法。"""


class ResumeMaterialNotFound(ResumeMaterialUseCaseError):
    """素材不存在或用户无权访问。"""


class ResumeMaterialImportFormatError(ResumeMaterialUseCaseError):
    """AI 提取素材结果格式异常。"""


class ResumeMaterialUseCases:
    """候选人素材库应用服务。"""

    async def create_material(self, *, request: dict, user_id: str) -> dict[str, object]:
        """创建 `material`。

        Args:
            request: 请求对象。
            user_id: 当前用户标识。
        """
        material_type = request.get("material_type")
        title = request.get("title")
        content = request.get("content")
        if not material_type or not title or not content:
            raise ResumeMaterialBadRequest(message="material_type, title, content 为必填字段")
        if material_type not in VALID_MATERIAL_TYPES:
            raise ResumeMaterialBadRequest(message=f"material_type 必须是 {VALID_MATERIAL_TYPES} 之一")

        material_id = await get_candidate_material_repo().create_material(
            user_id=user_id,
            material_type=material_type,
            title=title,
            content=content,
            structured_data=request.get("structured_data", {}),
            tags=request.get("tags", []),
            source_type=request.get("source_type", "manual"),
            source_resume_id=request.get("source_resume_id"),
            importance_score=request.get("importance_score", 0.5),
            confidence_score=request.get("confidence_score", 0.5),
            is_verified=request.get("is_verified", False),
        )
        return {"success": True, "material_id": material_id}

    async def import_materials_from_resume(self, *, request: dict, user_id: str) -> dict[str, object]:
        """异步执行 `import_materials_from_resume` 相关逻辑。

        Args:
            request: 请求对象。
            user_id: 当前用户标识。
        """
        resume_content = request.get("resume_content")
        if not resume_content:
            raise ResumeMaterialBadRequest(message="resume_content 为必填字段")
        api_config = request.get("api_config")
        if not api_config:
            raise ResumeMaterialBadRequest(message="请先配置 API Key")

        prompt = f"""请从以下简历中提取候选人的素材，按照以下类型分类：

1. tech_stack - 技术栈
2. project - 项目经历
3. internship - 实习经历
4. work_experience - 工作经验
5. education - 教育背景
6. certificate - 证书
7. highlight - 亮点/成就

## 简历内容
{resume_content}

## 输出要求
请以 JSON 数组格式输出每个素材，每个素材包含：
- material_type: 素材类型
- title: 简洁标题
- content: 详细内容
- tags: 相关标签列表

请严格以 JSON 格式输出，不要包含其他文本。"""
        response = await llms.invoke_text([HumanMessage(content=prompt)], api_config, channel="smart")
        result_text = self._strip_json_markdown(response.content.strip())
        try:
            materials_data = json.loads(result_text)
        except json.JSONDecodeError as exc:
            raise ResumeMaterialImportFormatError(message="AI 提取结果格式异常，请重试") from exc

        material_repo = get_candidate_material_repo()
        created_ids = []
        for material in materials_data:
            material_id = await material_repo.create_material(
                user_id=user_id,
                material_type=material.get("material_type", "highlight"),
                title=material.get("title", "未命名"),
                content=material.get("content", ""),
                tags=material.get("tags", []),
                source_type="ai_extract",
                confidence_score=0.7,
                is_verified=False,
            )
            created_ids.append(material_id)
        return {
            "success": True,
            "message": f"成功导入 {len(created_ids)} 个素材",
            "material_ids": created_ids,
        }

    async def list_materials(
        self,
        *,
        user_id: str,
        material_type: str | None,
        is_verified: bool | None,
        limit: int,
        offset: int,
    ) -> dict[str, object]:
        """列出 `materials`。

        Args:
            user_id: 当前用户标识。
            material_type: 调用方传入的 `material_type` 参数。
            is_verified: 调用方传入的 `is_verified` 参数。
            limit: 返回数量上限。
            offset: 分页偏移量。
        """
        try:
            materials = await get_candidate_material_repo().list_materials(
                user_id=user_id,
                material_type=material_type,
                is_verified=is_verified,
                limit=limit,
                offset=offset,
            )
            return {"success": True, "materials": materials}
        except Exception as exc:
            return {"success": False, "materials": [], "message": str(exc)}

    async def get_material(self, *, material_id: int, user_id: str) -> dict[str, object]:
        """获取 `material`。

        Args:
            material_id: material 标识。
            user_id: 当前用户标识。
        """
        material = await get_candidate_material_repo().get_material(material_id, user_id)
        if not material:
            raise ResumeMaterialNotFound(message="素材不存在")
        return {"success": True, "material": material}

    async def update_material(self, *, material_id: int, request: dict, user_id: str) -> dict[str, object]:
        """更新 `material`。

        Args:
            material_id: material 标识。
            request: 请求对象。
            user_id: 当前用户标识。
        """
        success = await get_candidate_material_repo().update_material(
            material_id=material_id,
            user_id=user_id,
            title=request.get("title"),
            content=request.get("content"),
            structured_data=request.get("structured_data"),
            tags=request.get("tags"),
            importance_score=request.get("importance_score"),
            confidence_score=request.get("confidence_score"),
            is_verified=request.get("is_verified"),
        )
        if not success:
            raise ResumeMaterialNotFound(message="素材不存在或无权更新")
        return {"success": True, "message": "更新成功"}

    async def delete_material(self, *, material_id: int, user_id: str) -> dict[str, object]:
        """删除 `material`。

        Args:
            material_id: material 标识。
            user_id: 当前用户标识。
        """
        success = await get_candidate_material_repo().delete_material(material_id, user_id)
        if not success:
            raise ResumeMaterialNotFound(message="素材不存在或无权删除")
        return {"success": True, "message": "删除成功"}

    @staticmethod
    def _strip_json_markdown(text: str) -> str:
        """执行 `_strip_json_markdown` 相关逻辑。

        Args:
            text: 文本内容。
        """
        if not text.startswith("```"):
            return text
        lines = text.split("\n")
        json_lines: list[str] = []
        in_block = False
        for line in lines:
            if line.startswith("```") and not in_block:
                in_block = True
                continue
            if line.startswith("```") and in_block:
                break
            if in_block:
                json_lines.append(line)
        return "\n".join(json_lines)


resume_material_use_cases = ResumeMaterialUseCases()
