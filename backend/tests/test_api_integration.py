"""
API 集成测试

使用 FastAPI TestClient 测试核心 API 端点。
- 部分测试使用真实 API Key（从 .env 读取）
- 数据库等外部依赖通过 mock 隔离

运行方式：
    cd backend
    uv run pytest tests/test_api_integration.py -v

只跑快速测试（不调 LLM）：
    uv run pytest tests/test_api_integration.py -v -m "fast"

只跑需要 LLM 的测试：
    uv run pytest tests/test_api_integration.py -v -m "llm"
"""

import os
import io
import sys
import types
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


# ============================================================================
# 预 Mock：在 import main 前解决循环导入 & 数据库依赖
# ============================================================================

def _pre_mock():
    """预注入 mock 模块，避免导入 main 时的循环依赖和数据库连接问题"""

    # -- 1. Mock session 子服务（解决 session_repo.py 循环导入）--
    class _FakeService:
        """Mock 服务类：委托给 AsyncMock，自动支持任意方法调用和 await"""
        def __init__(self, *args, **kwargs):
            object.__setattr__(self, "_mock", AsyncMock())

        async def get_session(self, *args, **kwargs):
            return await self._mock.get_session(*args, **kwargs)

        async def list_sessions(self, *args, **kwargs):
            return await self._mock.list_sessions(*args, **kwargs)

        async def get_user_profile(self, *args, **kwargs):
            return await self._mock.get_user_profile(*args, **kwargs)

        async def create_next_round(self, *args, **kwargs):
            return await self._mock.create_next_round(*args, **kwargs)

        def __getattr__(self, name):
            if name == "_mock":
                raise AttributeError(name)
            return getattr(object.__getattribute__(self, "_mock"), name)

    _sub_paths = [
        "app.infrastructure.db.repositories.session.repo_impl.base",
        "app.infrastructure.db.repositories.session.repo_impl.session_mgmt",
        "app.infrastructure.db.repositories.session.repo_impl.session_advanced",
        "app.infrastructure.db.repositories.session.repo_impl.message_mgmt",
        "app.infrastructure.db.repositories.session.repo_impl.profile_mgmt",
        "app.infrastructure.db.repositories.session.repo_impl.interview_plan",
    ]
    _names = [
        "SessionManagementService", "SessionAdvancedService",
        "MessageService", "ProfileService", "InterviewPlanService", "BaseService",
    ]
    for path in _sub_paths:
        if path not in sys.modules:
            mod = types.ModuleType(path)
            for name in _names:
                setattr(mod, name, _FakeService)
            sys.modules[path] = mod
        # 同时注入 backend.app.infrastructure.db.repositories... 路径
        backend_path = "backend." + path
        if backend_path not in sys.modules:
            sys.modules[backend_path] = sys.modules[path]

    # -- 2. 修复 conftest 的 asyncpg mock（缺少 connect 属性，需支持 await）--
    if "asyncpg" in sys.modules:
        apg = sys.modules["asyncpg"]

        class _FakeAsyncpgTransaction:
            async def start(self):
                return None

            async def commit(self):
                return None

            async def rollback(self):
                return None

        class _FakeAsyncpgConnection:
            """Enough asyncpg surface for accidental SQLAlchemy connection attempts.

            Do not use AsyncMock as the connection itself: asyncpg's SQLAlchemy
            dialect calls some methods synchronously (for example is_closed() and
            transaction()). If those become AsyncMock coroutines, later tests emit
            un-awaited coroutine warnings even when the DB call is caught.
            """

            def is_closed(self):
                return False

            def transaction(self, *args, **kwargs):
                return _FakeAsyncpgTransaction()

            def terminate(self):
                return None

            def add_listener(self, *args, **kwargs):
                return None

            def remove_listener(self, *args, **kwargs):
                return None

            def add_log_listener(self, *args, **kwargs):
                return None

            def remove_log_listener(self, *args, **kwargs):
                return None

            async def close(self, *args, **kwargs):
                return None

            async def set_type_codec(self, *args, **kwargs):
                return None

            async def execute(self, *args, **kwargs):
                return "OK"

            async def fetch(self, *args, **kwargs):
                return []

            async def fetchrow(self, *args, **kwargs):
                return None

            async def fetchval(self, *args, **kwargs):
                return None

            async def prepare(self, *args, **kwargs):
                raise RuntimeError("asyncpg is mocked in unit tests")

        if not hasattr(apg, "connect") or isinstance(apg.connect, MagicMock):
            apg.connect = AsyncMock(return_value=_FakeAsyncpgConnection())

    # -- 3. 预先导入 app.infrastructure.db.models，避免 backend.app.infrastructure.db.models 双重定义 --
    # （conftest 把 backend/ 加入 sys.path，导致两条导入路径）
    try:
        import app.infrastructure.db.models  # noqa: F401
    except Exception:
        pass
    if "app.infrastructure.db.models" in sys.modules:
        sys.modules.setdefault("backend.app.infrastructure.db.models", sys.modules["app.infrastructure.db.models"])


_pre_mock()


# ============================================================================
# 辅助函数：让 TestClient 跳过 lifespan 中的数据库操作
# ============================================================================

class _FakeMemoryService:
    """Mock 的 mem0 长期记忆服务"""
    is_enabled = False


def _enter_test_client(app) -> TestClient:
    """
    创建 TestClient，同时 mock 掉 lifespan 中的 init_db / mem0 等操作。
    用于跳过真实数据库连接。
    """
    # 关键 mock 路径（这些都是 lifespan 中调用的函数）
    # 注意：lifespan 内通过 `from app.infrastructure.db.models import init_db` 导入，
    # 所以需要 patch app.infrastructure.db.models.init_db（而非 app.infrastructure.db.models.base.init_db）
    lifespan_patches = [
        patch("app.infrastructure.db.models.init_db", new_callable=AsyncMock),
        patch("app.infrastructure.memory.get_agent_memory_service",
              new_callable=lambda: AsyncMock(return_value=_FakeMemoryService())),
        patch("app.infrastructure.memory.close_agent_memory_service", new_callable=AsyncMock),
        patch("app.infrastructure.memory.memory.close_checkpointer", new_callable=AsyncMock),
        patch("app.infrastructure.runtime.background_tasks.drain_background_tasks", new_callable=AsyncMock),
        patch("app.agents.interview.interview_graph.clear_graph_instances", MagicMock),
    ]

    # 启动所有 patch
    for p in lifespan_patches:
        p.start()

    try:
        client = TestClient(app)
        client.__enter__()
        yield client
        client.__exit__(None, None, None)
    finally:
        for p in lifespan_patches:
            p.stop()


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(scope="module")
def client():
    """创建 TestClient，自动加载 .env 配置"""
    from dotenv import load_dotenv

    env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    load_dotenv(env_path)

    from main import app

    yield from _enter_test_client(app)


# ============================================================================
# 1. 基础端点测试（fast）
# ============================================================================

@pytest.mark.fast
class TestHealthCheck:
    """健康检查和根路径"""

    def test_root_returns_api_info(self, client):
        """GET / 返回 API 基本信息"""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"
        assert "message" in data
        assert data["version"] == "1.0.0"

    def test_health_check(self, client):
        """GET /health 返回健康状态"""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_docs_available(self, client):
        """GET /docs 返回 Swagger 文档页"""
        response = client.get("/docs")
        assert response.status_code == 200
        assert "swagger" in response.text.lower() or "Swagger" in response.text

    def test_redoc_available(self, client):
        """GET /redoc 返回 ReDoc 文档页"""
        response = client.get("/redoc")
        assert response.status_code == 200


# ============================================================================
# 2. API 配置验证（llm — 使用真实 API Key）
# ============================================================================

@pytest.mark.llm
class TestConfigValidation:
    """验证 API 配置连通性"""

    def test_validate_with_env_credentials(self, client):
        """使用 .env 中的真实凭证验证配置"""
        payload = {
            "api_key": os.getenv("OPENAI_API_KEY", ""),
            "base_url": os.getenv("OPENAI_BASE_URL", ""),
            "model": os.getenv("FAST_MODEL") or os.getenv("SMART_MODEL", ""),
        }

        if not payload["api_key"]:
            pytest.skip("未设置 OPENAI_API_KEY，跳过 LLM 测试")

        response = client.post("/api/config/validate", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        assert "message" in data

        if data["success"]:
            print(f"  ✓ API 配置验证成功: {payload['model']}")
        else:
            print(f"  ⚠ API 配置验证失败: {data['message']}")

    def test_validate_invalid_api_key(self, client):
        """无效 API Key 应返回 success=False"""
        payload = {
            "api_key": "sk-invalid-key-12345",
            "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            "model": os.getenv("FAST_MODEL", "gpt-4o-mini"),
        }

        response = client.post("/api/config/validate", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "message" in data

    def test_validate_missing_fields(self, client):
        """缺少必填字段应返回 422"""
        payload = {"api_key": "sk-xxx"}
        response = client.post("/api/config/validate", json=payload)
        assert response.status_code == 422


# ============================================================================
# 3. 会话管理 CRUD（fast — mock 数据库）
# ============================================================================

@pytest.mark.fast
class TestSessionCRUD:
    """会话增删改查"""

    @pytest.fixture(autouse=True)
    def _setup_mock(self):
        """为每个测试方法注入 mock session_repo"""
        self.mock_repo = MagicMock()

        # 使用 dict 而非 MagicMock，确保 Pydantic 验证通过
        _session_dict = {
            "session_id": "test-001",
            "title": "测试面试",
            "created_at": "2026-06-22T00:00:00",
            "updated_at": "2026-06-22T00:00:00",
            "metadata": {
                "mode": "mock",
                "resume_filename": None,
                "resume_content": None,
                "job_description": None,
                "company_info": None,
                "question_count": 0,
                "max_questions": 5,
                "status": "active",
                "pinned": False,
                "series_id": None,
                "round_index": 1,
                "round_type": "tech_initial",
                "parent_session_id": None,
                "interview_plan": [],
            },
            "messages": [],
        }

        self.mock_repo.create_session = AsyncMock(return_value=_session_dict)
        self.mock_repo.get_session = AsyncMock(return_value=None)
        self.mock_repo.list_sessions = AsyncMock(return_value=[])
        self.mock_repo.get_session_count = AsyncMock(return_value=0)
        self.mock_repo.update_session = AsyncMock(return_value=None)
        self.mock_repo.delete_session = AsyncMock(return_value=True)
        self.mock_repo.add_message = AsyncMock(return_value=None)

        # 替换 sessions 应用层中的 SessionRepo 实例
        with patch("app.api.sessions.session_management_use_cases._session_repo", self.mock_repo):
            yield

    def test_create_session(self, client):
        """POST /api/sessions/ 创建新会话"""
        payload = {
            "mode": "mock",
            "title": "集成测试面试",
            "resume_filename": "test.pdf",
            "job_description": "Python 后端",
            "max_questions": 5,
        }
        response = client.post("/api/sessions/", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["session"]["session_id"] == "test-001"

    def test_list_sessions(self, client):
        """GET /api/sessions/ 获取会话列表"""
        self.mock_repo.list_sessions = AsyncMock(return_value=[
            {
                "session_id": "a", "title": "面试1", "mode": "mock",
                "status": "active", "message_count": 3, "question_count": 2,
                "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
                "pinned": False, "round_index": 1, "round_type": "tech_initial",
            },
            {
                "session_id": "b", "title": "面试2", "mode": "mock",
                "status": "completed", "message_count": 10, "question_count": 5,
                "created_at": "2026-01-02T00:00:00", "updated_at": "2026-01-02T00:00:00",
                "pinned": False, "round_index": 1, "round_type": "tech_initial",
            },
        ])
        self.mock_repo.get_session_count = AsyncMock(return_value=2)

        response = client.get("/api/sessions/")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["total"] == 2
        assert len(data["sessions"]) == 2

    def test_get_session_404(self, client):
        """GET /api/sessions/{id} 不存在返回 404"""
        response = client.get("/api/sessions/non-existent")
        assert response.status_code == 404
        data = response.json()
        assert data["error"] == "NotFound"

    def test_update_session(self, client):
        """PATCH /api/sessions/{id} 更新会话"""
        _updated = {
            "session_id": "test-1",
            "title": "新标题",
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
            "metadata": {
                "mode": "mock", "resume_filename": None, "resume_content": None,
                "job_description": None, "company_info": None, "question_count": 0,
                "max_questions": 5, "status": "active", "pinned": False,
                "series_id": None, "round_index": 1, "round_type": "tech_initial",
                "parent_session_id": None, "interview_plan": [],
            },
            "messages": [],
        }
        self.mock_repo.update_session = AsyncMock(return_value=_updated)

        response = client.patch("/api/sessions/test-1", json={
            "title": "新标题", "status": None, "metadata": None,
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_delete_session(self, client):
        """DELETE /api/sessions/{id} 删除会话"""
        self.mock_repo.get_session = AsyncMock(return_value=MagicMock(session_id="test-1"))
        response = client.delete("/api/sessions/test-1")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_delete_session_404(self, client):
        """DELETE 不存在的会话返回 404"""
        self.mock_repo.get_session = AsyncMock(return_value=None)
        response = client.delete("/api/sessions/nonexistent")
        assert response.status_code == 404


# ============================================================================
# 4. 文件上传测试（fast）
# ============================================================================

@pytest.mark.fast
class TestFileUpload:
    """简历文件上传"""

    def test_upload_txt(self, client):
        """上传 .txt 简历"""
        content = "姓名：张三\n工作经验：3年Python后端\n技能：Django, FastAPI, PostgreSQL"
        file = io.BytesIO(content.encode("utf-8"))
        response = client.post(
            "/api/upload/resume",
            files={"file": ("resume.txt", file, "text/plain")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["text_content"]) > 0

    def test_upload_unsupported_format(self, client):
        """不支持的文件格式返回 400"""
        file = io.BytesIO(b"fake image")
        response = client.post(
            "/api/upload/resume",
            files={"file": ("photo.jpg", file, "image/jpeg")},
        )
        assert response.status_code == 400
        # 自定义 HTTPException handler 把 detail dict 展平为 response body
        assert response.json()["error"] == "UnsupportedFileType"

    def test_upload_no_file(self, client):
        """无文件返回 422"""
        response = client.post("/api/upload/resume")
        assert response.status_code == 422

    def test_upload_oversized(self, client):
        """超大文件返回 413"""
        large = io.BytesIO(b"x" * (15 * 1024 * 1024))
        response = client.post(
            "/api/upload/resume",
            files={"file": ("large.txt", large, "text/plain")},
        )
        assert response.status_code == 413

    def test_upload_minimal_pdf(self, client):
        """上传最小合法 PDF"""
        minimal_pdf = (
            b"%PDF-1.4\n"
            b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<<>>>>endobj\n"
            b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n"
            b"0000000058 00000 n \n0000000115 00000 n \n"
            b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n190\n%%EOF"
        )
        file = io.BytesIO(minimal_pdf)
        response = client.post(
            "/api/upload/resume",
            files={"file": ("minimal.pdf", file, "application/pdf")},
        )
        # 最小 PDF 可能无文本内容，返回 200 或 400 均可
        assert response.status_code in [200, 400]


# ============================================================================
# 5. 错误响应格式（fast）
# ============================================================================

@pytest.mark.fast
class TestErrorResponseFormat:
    """错误响应格式验证"""

    @pytest.fixture(autouse=True)
    def _mock_session(self):
        """Mock 当前会话管理用例，确保 get_session 走 404 分支。"""
        from app.workflows.interview.sessions import SessionManagementNotFound

        mock_use_cases = MagicMock()
        mock_use_cases.get_session = AsyncMock(
            side_effect=SessionManagementNotFound(message="会话 nonexistent 不存在")
        )
        with patch("app.api.sessions.session_management_use_cases", mock_use_cases):
            yield

    def test_404_format(self, client):
        """404 错误有标准格式"""
        response = client.get("/api/sessions/nonexistent")
        assert response.status_code == 404
        data = response.json()
        assert "error" in data
        assert "message" in data

    def test_422_format(self, client):
        """422 验证错误"""
        response = client.post(
            "/api/sessions/",
            content=b"not json {{{",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code in [400, 422]


# ============================================================================
# 6. OpenAPI 文档（fast）
# ============================================================================

@pytest.mark.fast
class TestOpenAPI:
    """OpenAPI schema 和文档端点"""

    def test_openapi_json(self, client):
        """GET /openapi.json 返回有效 schema"""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        assert "openapi" in schema
        assert "paths" in schema
        # 验证关键路由存在
        paths = schema["paths"]
        assert "/health" in paths
        assert "/api/config/validate" in paths
        assert "/api/sessions/" in paths
        assert "/api/upload/resume" in paths
