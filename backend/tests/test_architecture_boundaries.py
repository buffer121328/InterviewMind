"""关键依赖方向的轻量架构测试。"""

import ast
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
BACKEND_APP = BACKEND_ROOT / "app"


def test_backend_root_only_contains_project_config_files():
    """后端根目录只保留项目/构建/测试配置；应用入口放入 app 或 scripts。"""
    allowed = {
        ".dockerignore",
        "Dockerfile",
        "__init__.py",
        "alembic.ini",
        "conftest.py",
        "pyproject.toml",
        "pytest.ini",
        "uv.lock",
    }
    actual = {path.name for path in BACKEND_ROOT.iterdir() if path.is_file()}
    assert actual <= allowed


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
        elif isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
    return modules


def test_migration_legacy_shim_files_are_removed():
    """迁移完成后不保留只做旧导入路径转发的兼容壳。"""
    legacy_paths = {
        BACKEND_APP / "agents" / "definitions.py",
        BACKEND_APP / "agents" / "interview" / "prompts.py",
        BACKEND_APP / "agents" / "interview" / "question_defaults.py",
        BACKEND_APP / "agents" / "interview" / "runtime.py",
        BACKEND_APP / "agents" / "interview" / "tools.py",
        BACKEND_APP / "agents" / "job_application",
        BACKEND_APP / "agents" / "resume" / "resume_optimizer_graph.py",
        BACKEND_APP / "agents" / "resume_analyzer",
        BACKEND_APP / "agents" / "resume_generator",
        BACKEND_APP / "agents" / "resume_optimizer",
        BACKEND_APP / "infrastructure" / "runtime" / "definitions.py",
        BACKEND_APP / "infrastructure" / "runtime" / "agent_runs" / "executors.py",
        BACKEND_APP / "infrastructure" / "runtime" / "agent_runs" / "interview_start.py",
        BACKEND_APP / "infrastructure" / "runtime" / "memory",
        BACKEND_APP / "prompts" / "runtime",
        BACKEND_APP / "tools" / "runtime",
        BACKEND_APP / "workflows" / "question_bank_support" / "session_archive.py",
    }
    remaining: list[str] = []
    for path in legacy_paths:
        if path.is_file():
            remaining.append(str(path.relative_to(BACKEND_ROOT)))
        elif path.is_dir():
            remaining.extend(
                str(child.relative_to(BACKEND_ROOT))
                for child in path.rglob("*.py")
                if "__pycache__" not in child.parts
            )
    assert sorted(remaining) == []


def test_code_does_not_import_removed_migration_modules():
    """新代码应直接引用 domain/workflows/repository 中的新位置。"""
    removed_modules = (
        "app.agents.definitions",
        "app.infrastructure.runtime.definitions",
        "app.infrastructure.runtime.agent_runs.executors",
        "app.infrastructure.runtime.agent_runs.interview_start",
        "app.workflows.question_bank_support.session_archive",
        "app.agents.interview.prompts",
        "app.agents.interview.question_defaults",
        "app.agents.interview.runtime",
        "app.agents.interview.tools",
        "app.agents.job_application",
        "app.agents.resume.resume_optimizer_graph",
        "app.agents.resume_analyzer",
        "app.agents.resume_generator",
        "app.agents.resume_optimizer",
        "app.infrastructure.runtime.memory",
        "app.prompts.runtime",
        "app.tools.runtime",
    )
    violations: list[str] = []
    for root in (BACKEND_APP, BACKEND_ROOT / "tests", BACKEND_ROOT / "evaluation"):
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            for module in _imports(path):
                if module.startswith(removed_modules):
                    violations.append(f"{path.relative_to(BACKEND_ROOT)} -> {module}")
    assert violations == []


def test_repositories_do_not_depend_on_upper_layers():
    violations: list[str] = []
    forbidden = ("app.api", "app.agents", "app.workflows", "app.infrastructure.runtime")
    for path in (BACKEND_APP / "infrastructure" / "db" / "repositories").rglob("*.py"):
        for module in _imports(path):
            if module.startswith(forbidden):
                violations.append(f"{path.relative_to(BACKEND_APP)} -> {module}")
    assert violations == []


def test_runtime_does_not_import_api_layer():
    violations: list[str] = []
    forbidden = ("app.api",)
    for path in (BACKEND_APP / "infrastructure" / "runtime").rglob("*.py"):
        for module in _imports(path):
            if module.startswith(forbidden):
                violations.append(f"{path.relative_to(BACKEND_APP)} -> {module}")
    assert violations == []


def test_app_code_uses_app_package_imports():
    violations: list[str] = []
    forbidden = ("backend.",)
    for path in BACKEND_APP.rglob("*.py"):
        for module in _imports(path):
            if module.startswith(forbidden) or module == "backend":
                violations.append(f"{path.relative_to(BACKEND_APP)} -> {module}")
    assert violations == []


def test_agents_do_not_depend_on_agent_run_runtime():
    """Agent 图/工具层不应该反向认识 AgentRun 队列、worker、dispatcher。"""
    violations: list[str] = []
    forbidden = ("app.infrastructure.runtime.agent_runs",)
    for path in (BACKEND_APP / "agents").rglob("*.py"):
        for module in _imports(path):
            if module.startswith(forbidden):
                violations.append(f"{path.relative_to(BACKEND_APP)} -> {module}")
    assert violations == []


def test_agent_run_runtime_does_not_host_business_agent_tasks():
    """AgentRun runtime 只负责状态/队列；具体业务任务应放在 workflows.agent_tasks。"""
    violations: list[str] = []
    allowed: set[str] = set()
    for path in (BACKEND_APP / "infrastructure" / "runtime" / "agent_runs").rglob("*.py"):
        for module in _imports(path):
            if module.startswith("app.agents"):
                item = f"{path.relative_to(BACKEND_APP)} -> {module}"
                if item not in allowed:
                    violations.append(item)
    assert violations == []


def test_agent_task_registry_uses_domain_task_constants_not_runtime_service():
    """任务注册表不应为拿常量而依赖 AgentRunService，避免 worker 启动期耦合。"""
    registry = BACKEND_APP / "workflows" / "agent_tasks" / "registry.py"
    forbidden = ("app.infrastructure.runtime.agent_runs.service",)
    violations = [module for module in _imports(registry) if module.startswith(forbidden)]
    assert violations == []


def test_agent_runs_api_uses_workflow_and_domain_not_runtime_service():
    """AgentRun HTTP 路由不应为任务类型常量直接依赖 runtime service。"""
    path = BACKEND_APP / "api" / "agent_runs.py"
    forbidden = ("app.infrastructure.runtime.agent_runs.service",)
    violations = [module for module in _imports(path) if module.startswith(forbidden)]
    assert violations == []


def test_api_routes_do_not_depend_on_agents_or_infrastructure():
    """HTTP 路由只做传输适配，不直接耦合 agents/infrastructure 实现。"""
    violations: list[str] = []
    forbidden = ("app.agents", "app.infrastructure")
    for path in (BACKEND_APP / "api").rglob("*.py"):
        for module in _imports(path):
            if module.startswith(forbidden):
                violations.append(f"{path.relative_to(BACKEND_APP)} -> {module}")
    assert violations == []
