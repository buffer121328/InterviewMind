"""
JD 匹配分析 API 测试
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock

# 导入主应用
from app.main import app

client = TestClient(app)

TEST_API_CONFIG = {
    "smart": {
        "api_key": "test-api-key",
        "base_url": "https://api.example.test/v1",
        "model": "test-smart-model",
    },
    "fast": {
        "api_key": "test-api-key",
        "base_url": "https://api.example.test/v1",
        "model": "test-fast-model",
    },
}


@pytest.fixture
def jd_match_dependencies(monkeypatch):
    """为 API 测试隔离 LLM 与 PostgreSQL 结果仓库。"""
    from ai.workflows.resume import jd_match as jd_match_app

    analyze = AsyncMock()
    repository = AsyncMock()
    repository.save_result.return_value = 1
    repository.list_results.return_value = []
    repository.get_result.return_value = None
    repository.delete_result.return_value = False

    monkeypatch.setattr(jd_match_app, "analyze_jd_match", analyze)
    monkeypatch.setattr(jd_match_app, "get_jd_analysis_repo", lambda: repository)
    return analyze, repository




class _FakeSession:
    def __init__(self):
        self.calls = []

    async def commit(self):
        self.calls.append("commit")

    async def close(self):
        self.calls.append("close")

    async def rollback(self):
        self.calls.append("rollback")

class TestJDMatchAPI:
    """JD 匹配分析 API 测试类"""
    
    def test_jd_match_success(self, jd_match_dependencies):
        """测试 JD 匹配分析成功"""
        # 准备 mock 返回值
        analyze, _ = jd_match_dependencies
        analyze.return_value = {
            "overall_match_score": 75.5,
            "skill_match_score": 80.0,
            "project_match_score": 70.0,
            "experience_match_score": 75.0,
            "education_match_score": 85.0,
            "matched_keywords": ["Python", "FastAPI", "PostgreSQL"],
            "missing_keywords": ["Kubernetes", "Docker"],
            "strengths": ["技术栈匹配度高", "项目经验丰富"],
            "risks": ["缺少容器化经验"],
            "priority_actions": ["补充 Docker 知识", "学习 Kubernetes 基础"],
            "selection_hints": {
                "recommended_projects": ["项目A", "项目B"],
                "recommended_skills": ["Python", "FastAPI"],
                "rewrite_focus": ["强调 API 设计能力"]
            }
        }
        
        # 准备请求
        payload = {
            "resume_content": "我是一名 Python 开发工程师，有 3 年 FastAPI 开发经验",
            "job_description": "招聘 Python 后端开发工程师，要求熟悉 FastAPI 和 PostgreSQL",
            "api_config": TEST_API_CONFIG,
        }
        
        # 执行
        response = client.post(
            "/api/resume/jd-match",
            json=payload,
            headers={"X-User-ID": "test_user"}
        )
        
        # 验证
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "result" in data
        assert "analysis_id" in data
        assert data["result"]["overall_match_score"] == 75.5
        assert len(data["result"]["matched_keywords"]) == 3
    

    def test_jd_match_success_saves_with_unit_of_work_session(self, jd_match_dependencies, monkeypatch):
        from ai.workflows.resume import jd_match as jd_match_app

        analyze, repository = jd_match_dependencies
        analyze.return_value = {
            "overall_match_score": 75.5,
            "skill_match_score": 80.0,
            "project_match_score": 70.0,
            "experience_match_score": 75.0,
            "education_match_score": 85.0,
            "matched_keywords": ["Python"],
            "missing_keywords": [],
            "strengths": [],
            "risks": [],
            "priority_actions": [],
            "selection_hints": {},
        }
        session = _FakeSession()
        monkeypatch.setattr(jd_match_app, "async_session", lambda: session)

        payload = {
            "resume_content": "我是一名 Python 开发工程师",
            "job_description": "招聘 Python 开发工程师",
            "api_config": TEST_API_CONFIG,
        }
        response = client.post("/api/resume/jd-match", json=payload, headers={"X-User-ID": "test_user"})

        assert response.status_code == 200
        assert repository.save_result.await_args.kwargs["session"] is session

    def test_jd_match_missing_resume(self, jd_match_dependencies):
        """测试缺少简历内容"""
        # 准备
        payload = {
            "resume_content": "",
            "job_description": "招聘 Python 开发工程师",
            "api_config": TEST_API_CONFIG,
        }
        
        # 执行
        response = client.post(
            "/api/resume/jd-match",
            json=payload,
            headers={"X-User-ID": "test_user"}
        )
        
        # 验证
        assert response.status_code == 400
        data = response.json()
        assert "简历内容" in data["message"]
    
    def test_jd_match_missing_jd(self, jd_match_dependencies):
        """测试缺少 JD 内容"""
        # 准备
        payload = {
            "resume_content": "我是一名 Python 开发工程师",
            "job_description": "",
            "api_config": TEST_API_CONFIG,
        }
        
        # 执行
        response = client.post(
            "/api/resume/jd-match",
            json=payload,
            headers={"X-User-ID": "test_user"}
        )
        
        # 验证
        assert response.status_code == 400
        data = response.json()
        assert "职位描述" in data["message"]
    
    def test_jd_match_missing_api_config(self, jd_match_dependencies):
        """测试缺少 API 配置"""
        # 准备
        payload = {
            "resume_content": "我是一名 Python 开发工程师",
            "job_description": "招聘 Python 开发工程师"
        }
        
        # 执行
        response = client.post(
            "/api/resume/jd-match",
            json=payload,
            headers={"X-User-ID": "test_user"}
        )
        
        # 验证
        assert response.status_code == 400
        data = response.json()
        assert "API Key" in data["message"]
    
    def test_list_jd_match_results(self, jd_match_dependencies):
        """测试获取 JD 匹配分析历史列表"""
        # 执行
        response = client.get(
            "/api/resume/jd-match",
            headers={"X-User-ID": "test_user"}
        )
        
        # 验证
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "results" in data
        assert isinstance(data["results"], list)
    
    def test_get_jd_match_result_not_found(self, jd_match_dependencies):
        """测试获取不存在的分析结果"""
        # 执行
        response = client.get(
            "/api/resume/jd-match/99999",
            headers={"X-User-ID": "test_user"}
        )
        
        # 验证
        assert response.status_code == 404
    
    def test_delete_jd_match_result_not_found(self, jd_match_dependencies):
        """测试删除不存在的分析结果"""
        # 执行
        response = client.delete(
            "/api/resume/jd-match/99999",
            headers={"X-User-ID": "test_user"}
        )
        
        # 验证
        assert response.status_code == 404


class TestJDMatchModels:
    """JD 匹配分析模型测试类"""
    
    def test_jd_match_request_validation(self):
        """测试请求模型验证"""
        from app.schemas.jd_schemas import JDMatchRequest
        
        # 有效请求
        valid_request = JDMatchRequest(
            resume_content="测试简历",
            job_description="测试 JD",
            api_config=TEST_API_CONFIG,
        )
        assert valid_request.resume_content == "测试简历"
        assert valid_request.resume_source_type == "manual_input"  # 默认值
        
        # 带可选字段
        full_request = JDMatchRequest(
            resume_content="测试简历",
            job_description="测试 JD",
            user_id="custom_user",
            resume_source_type="uploaded_resume",
            resume_source_id=123,
            api_config=TEST_API_CONFIG,
        )
        assert full_request.user_id == "custom_user"
        assert full_request.resume_source_id == 123
    
    def test_jd_match_result_validation(self):
        """测试结果模型验证"""
        from app.schemas.jd_schemas import JDMatchResult
        
        # 有效结果
        valid_result = JDMatchResult(
            overall_match_score=75.5,
            skill_match_score=80.0,
            project_match_score=70.0,
            experience_match_score=75.0,
            education_match_score=85.0,
            matched_keywords=["Python", "FastAPI"],
            missing_keywords=["Kubernetes"],
            strengths=["技术栈匹配"],
            risks=["缺少容器经验"],
            priority_actions=["学习 Docker"],
            selection_hints={"recommended_projects": ["项目A"]}
        )
        assert valid_result.overall_match_score == 75.5
        assert len(valid_result.matched_keywords) == 2
        
        # 测试分数边界
        with pytest.raises(Exception):
            JDMatchResult(
                overall_match_score=150,  # 超出范围
                skill_match_score=80.0,
                project_match_score=70.0,
                experience_match_score=75.0,
                education_match_score=85.0
            )
    
    def test_jd_match_response_validation(self):
        """测试响应模型验证"""
        from app.schemas.jd_schemas import JDMatchResponse, JDMatchResult
        
        # 成功响应
        result = JDMatchResult(
            overall_match_score=75.5,
            skill_match_score=80.0,
            project_match_score=70.0,
            experience_match_score=75.0,
            education_match_score=85.0
        )
        success_response = JDMatchResponse(
            success=True,
            result=result,
            analysis_id=123
        )
        assert success_response.success is True
        assert success_response.analysis_id == 123
        
        # 失败响应
        error_response = JDMatchResponse(
            success=False,
            message="分析失败"
        )
        assert error_response.success is False
        assert error_response.result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
