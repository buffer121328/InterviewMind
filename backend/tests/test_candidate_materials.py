"""
候选人素材库 API 测试
"""

import pytest
from fastapi.testclient import TestClient
from types import SimpleNamespace

# 导入主应用
from backend.main import app

client = TestClient(app)


class InMemoryMaterialRepo:
    """隔离素材接口测试，避免依赖外部 PostgreSQL。"""

    def __init__(self):
        self._materials = {}
        self._next_id = 1

    async def create_material(self, **kwargs):
        material_id = self._next_id
        self._next_id += 1
        self._materials[material_id] = {"id": material_id, **kwargs}
        return material_id

    async def list_materials(
        self,
        user_id,
        material_type=None,
        is_verified=None,
        limit=100,
        offset=0,
    ):
        materials = [
            material for material in self._materials.values()
            if material["user_id"] == user_id
        ]
        if material_type:
            materials = [m for m in materials if m["material_type"] == material_type]
        if is_verified is not None:
            materials = [m for m in materials if m["is_verified"] is is_verified]
        return materials[offset:offset + limit]

    async def get_material(self, material_id, user_id):
        material = self._materials.get(material_id)
        return material if material and material["user_id"] == user_id else None

    async def update_material(self, material_id, user_id, **kwargs):
        material = await self.get_material(material_id, user_id)
        if not material:
            return False
        material.update({key: value for key, value in kwargs.items() if value is not None})
        return True

    async def delete_material(self, material_id, user_id):
        material = await self.get_material(material_id, user_id)
        if not material:
            return False
        del self._materials[material_id]
        return True


@pytest.fixture
def material_repo(monkeypatch):
    from app.repositories.resume import candidate_material_repo

    repo = InMemoryMaterialRepo()
    monkeypatch.setattr(candidate_material_repo, "get_candidate_material_repo", lambda: repo)
    return repo


@pytest.fixture
def assembly_services(monkeypatch):
    from app.services.resume import resume_assembler

    async def select_empty_materials(**_kwargs):
        return SimpleNamespace(
            selected_material_ids=[],
            selection_reason="素材库为空，请先添加素材",
            assembled_outline={},
        )

    async def list_empty_results(**_kwargs):
        return []

    async def get_missing_result(*_args, **_kwargs):
        return None

    monkeypatch.setattr(resume_assembler, "select_materials_for_jd", select_empty_materials)
    monkeypatch.setattr(resume_assembler, "list_assembly_results", list_empty_results)
    monkeypatch.setattr(resume_assembler, "get_assembly_result", get_missing_result)


class TestCandidateMaterialsAPI:
    """候选人素材库 API 测试类"""
    
    def test_create_material_success(self, material_repo):
        """测试创建素材成功"""
        # 准备
        payload = {
            "material_type": "project",
            "title": "测试项目",
            "content": "这是一个测试项目的内容",
            "tags": ["测试", "项目"],
            "importance_score": 0.8,
            "confidence_score": 0.9,
            "is_verified": True
        }
        
        # 执行
        response = client.post(
            "/api/resume/materials",
            json=payload,
            headers={"X-User-ID": "test_user"}
        )
        
        # 验证
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "material_id" in data
    
    def test_create_material_missing_fields(self, material_repo):
        """测试创建素材缺少必填字段"""
        # 准备
        payload = {
            "material_type": "project",
            # 缺少 title 和 content
        }
        
        # 执行
        response = client.post(
            "/api/resume/materials",
            json=payload,
            headers={"X-User-ID": "test_user"}
        )
        
        # 验证
        assert response.status_code == 400
        data = response.json()
        assert "material_type, title, content" in data["message"]
    
    def test_create_material_invalid_type(self, material_repo):
        """测试创建素材类型无效"""
        # 准备
        payload = {
            "material_type": "invalid_type",
            "title": "测试项目",
            "content": "这是一个测试项目的内容"
        }
        
        # 执行
        response = client.post(
            "/api/resume/materials",
            json=payload,
            headers={"X-User-ID": "test_user"}
        )
        
        # 验证
        assert response.status_code == 400
        data = response.json()
        assert "material_type" in data["message"]
    
    def test_list_materials_success(self, material_repo):
        """测试获取素材列表成功"""
        # 执行
        response = client.get(
            "/api/resume/materials",
            headers={"X-User-ID": "test_user"}
        )
        
        # 验证
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "materials" in data
    
    def test_list_materials_with_filter(self, material_repo):
        """测试带过滤条件获取素材列表"""
        # 执行
        response = client.get(
            "/api/resume/materials?material_type=project&is_verified=true",
            headers={"X-User-ID": "test_user"}
        )
        
        # 验证
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
    
    def test_get_material_success(self, material_repo):
        """测试获取单个素材成功"""
        # 先创建一个素材
        create_response = client.post(
            "/api/resume/materials",
            json={
                "material_type": "tech_stack",
                "title": "Python",
                "content": "Python 编程语言",
                "tags": ["Python", "编程"]
            },
            headers={"X-User-ID": "test_user"}
        )
        material_id = create_response.json()["material_id"]
        
        # 执行
        response = client.get(
            f"/api/resume/materials/{material_id}",
            headers={"X-User-ID": "test_user"}
        )
        
        # 验证
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["material"]["id"] == material_id
    
    def test_get_material_not_found(self, material_repo):
        """测试获取不存在的素材"""
        # 执行
        response = client.get(
            "/api/resume/materials/99999",
            headers={"X-User-ID": "test_user"}
        )
        
        # 验证
        assert response.status_code == 404
    
    def test_update_material_success(self, material_repo):
        """测试更新素材成功"""
        # 先创建一个素材
        create_response = client.post(
            "/api/resume/materials",
            json={
                "material_type": "project",
                "title": "原始标题",
                "content": "原始内容"
            },
            headers={"X-User-ID": "test_user"}
        )
        material_id = create_response.json()["material_id"]
        
        # 执行更新
        update_payload = {
            "title": "更新后的标题",
            "content": "更新后的内容",
            "is_verified": True
        }
        response = client.put(
            f"/api/resume/materials/{material_id}",
            json=update_payload,
            headers={"X-User-ID": "test_user"}
        )
        
        # 验证
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        
        # 验证更新结果
        get_response = client.get(
            f"/api/resume/materials/{material_id}",
            headers={"X-User-ID": "test_user"}
        )
        material = get_response.json()["material"]
        assert material["title"] == "更新后的标题"
        assert material["is_verified"] is True
    
    def test_delete_material_success(self, material_repo):
        """测试删除素材成功"""
        # 先创建一个素材
        create_response = client.post(
            "/api/resume/materials",
            json={
                "material_type": "highlight",
                "title": "待删除素材",
                "content": "这个素材将被删除"
            },
            headers={"X-User-ID": "test_user"}
        )
        material_id = create_response.json()["material_id"]
        
        # 执行删除
        response = client.delete(
            f"/api/resume/materials/{material_id}",
            headers={"X-User-ID": "test_user"}
        )
        
        # 验证
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        
        # 验证确实已删除
        get_response = client.get(
            f"/api/resume/materials/{material_id}",
            headers={"X-User-ID": "test_user"}
        )
        assert get_response.status_code == 404


class TestAssemblyAPI:
    """简历组装 API 测试类"""
    
    def test_assemble_without_materials(self, assembly_services):
        """测试没有素材时组装"""
        # 准备
        payload = {
            "job_description": "测试 JD",
            "api_config": {
                "smartModelId": "test",
                "fastModelId": "test"
            }
        }
        
        # 执行
        response = client.post(
            "/api/resume/assemble",
            json=payload,
            headers={"X-User-ID": "test_user_empty"}
        )
        
        # 验证
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["selected_material_ids"] == []
    
    def test_list_assembly_results(self, assembly_services):
        """测试获取组装结果列表"""
        # 执行
        response = client.get(
            "/api/resume/assemble",
            headers={"X-User-ID": "test_user"}
        )
        
        # 验证
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "results" in data
    
    def test_get_assembly_result_not_found(self, assembly_services):
        """测试获取不存在的组装结果"""
        # 执行
        response = client.get(
            "/api/resume/assemble/99999",
            headers={"X-User-ID": "test_user"}
        )
        
        # 验证
        assert response.status_code == 404


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
