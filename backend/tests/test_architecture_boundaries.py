"""关键依赖方向的轻量架构测试。"""

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
BACKEND_APP = BACKEND_ROOT / "app"
BACKEND_AI = BACKEND_ROOT / "ai"
BACKEND_INTEGRATIONS = BACKEND_ROOT / "integrations"


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
        BACKEND_APP / "infrastructure",
        BACKEND_AI / "agents" / "definitions.py",
        BACKEND_AI / "agents" / "interview" / "prompts.py",
        BACKEND_AI / "agents" / "interview" / "question_defaults.py",
        BACKEND_AI / "agents" / "interview" / "runtime.py",
        BACKEND_AI / "agents" / "interview" / "tools.py",
        BACKEND_AI / "agents" / "job_application",
        BACKEND_AI / "agents" / "resume" / "resume_optimizer_graph.py",
        BACKEND_AI / "agents" / "resume_analyzer",
        BACKEND_AI / "agents" / "resume_generator",
        BACKEND_AI / "agents" / "resume_optimizer",
        BACKEND_AI / "runtime" / "definitions.py",
        BACKEND_AI / "runtime" / "agent_runs" / "executors.py",
        BACKEND_AI / "runtime" / "agent_runs" / "interview_start.py",
        BACKEND_AI / "runtime" / "agent_runs" / "crypto.py",
        BACKEND_AI / "runtime" / "memory",
        BACKEND_AI / "prompts" / "runtime",
        BACKEND_AI / "tools" / "runtime",
        BACKEND_AI / "workflows" / "question_bank_support" / "session_archive.py",
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
        "ai.agents.definitions",
        "ai.runtime.definitions",
        "ai.runtime.agent_runs.executors",
        "ai.runtime.agent_runs.interview_start",
        "ai.runtime.agent_runs.crypto",
        "ai.workflows.question_bank_support.session_archive",
        "ai.agents.interview.prompts",
        "ai.agents.interview.question_defaults",
        "ai.agents.interview.runtime",
        "ai.agents.interview.tools",
        "ai.agents.job_application",
        "ai.agents.resume.resume_optimizer_graph",
        "ai.agents.resume_analyzer",
        "ai.agents.resume_generator",
        "ai.agents.resume_optimizer",
        "ai.runtime.memory",
        "ai.runtime.models.policies",
        "ai.runtime.authoritative_context",
        "ai.runtime.background_tasks",
        "ai.runtime.call_budgets",
        "ai.runtime.context_assembler",
        "ai.runtime.deadlines",
        "ai.runtime.error_classification",
        "ai.runtime.evidence",
        "ai.runtime.guardrails",
        "ai.runtime.runtime_gate",
        "ai.prompts.runtime",
        "ai.tools.runtime",
    )
    violations: list[str] = []
    for root in (BACKEND_APP, BACKEND_AI, BACKEND_ROOT / "tests", BACKEND_ROOT / "evaluation"):
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            for module in _imports(path):
                if module.startswith(removed_modules):
                    violations.append(f"{path.relative_to(BACKEND_ROOT)} -> {module}")
    assert violations == []


def test_repositories_do_not_depend_on_upper_layers():
    violations: list[str] = []
    forbidden = ("app.api", "ai.agents", "ai.workflows", "ai.runtime")
    for path in (BACKEND_APP / "db" / "repositories").rglob("*.py"):
        for module in _imports(path):
            if module.startswith(forbidden):
                violations.append(f"{path.relative_to(BACKEND_ROOT)} -> {module}")
    assert violations == []


def test_runtime_does_not_import_api_layer():
    violations: list[str] = []
    forbidden = ("app.api",)
    for path in (BACKEND_AI / "runtime").rglob("*.py"):
        for module in _imports(path):
            if module.startswith(forbidden):
                violations.append(f"{path.relative_to(BACKEND_ROOT)} -> {module}")
    assert violations == []


def test_app_code_uses_package_imports():
    violations: list[str] = []
    forbidden = ("backend.",)
    for root in (BACKEND_APP, BACKEND_AI, BACKEND_INTEGRATIONS):
        for path in root.rglob("*.py"):
            for module in _imports(path):
                if module.startswith(forbidden) or module == "backend":
                    violations.append(f"{path.relative_to(BACKEND_ROOT)} -> {module}")
    assert violations == []


def test_agents_do_not_depend_on_agent_run_runtime():
    """Agent 图/工具层不应该反向认识 AgentRun 队列、worker、dispatcher。"""
    violations: list[str] = []
    forbidden = ("ai.runtime.agent_runs",)
    for path in (BACKEND_AI / "agents").rglob("*.py"):
        for module in _imports(path):
            if module.startswith(forbidden):
                violations.append(f"{path.relative_to(BACKEND_ROOT)} -> {module}")
    assert violations == []


def test_runtime_graph_registry_does_not_import_business_agents():
    """通用图注册表不应反向导入具体业务 Agent。"""

    violations: list[str] = []
    for path in (BACKEND_AI / "runtime" / "graphs").rglob("*.py"):
        for module in _imports(path):
            if module.startswith("ai.agents"):
                violations.append(f"{path.relative_to(BACKEND_ROOT)} -> {module}")
    assert violations == []


def test_agent_run_runtime_does_not_depend_on_workflow_composition():
    """持久化 AgentRun runtime 不得反向依赖 production queue/workflow 组合。"""

    violations: list[str] = []
    forbidden = ("ai.workflows",)
    for path in (BACKEND_AI / "runtime" / "agent_runs").rglob("*.py"):
        for module in _imports(path):
            if module.startswith(forbidden):
                violations.append(f"{path.relative_to(BACKEND_ROOT)} -> {module}")
    assert violations == []


def test_agent_run_runtime_does_not_host_business_agent_tasks():
    """AgentRun runtime 只负责状态/队列；具体业务任务应放在 workflows.agent_runs.tasks。"""
    violations: list[str] = []
    allowed: set[str] = set()
    for path in (BACKEND_AI / "runtime" / "agent_runs").rglob("*.py"):
        for module in _imports(path):
            if module.startswith("ai.agents"):
                item = f"{path.relative_to(BACKEND_ROOT)} -> {module}"
                if item not in allowed:
                    violations.append(item)
    assert violations == []


def test_agent_task_registry_uses_domain_task_constants_not_runtime_service():
    """任务注册表不应为拿常量而依赖 AgentRunService，避免 worker 启动期耦合。"""
    registry = BACKEND_AI / "workflows" / "agent_runs" / "catalog.py"
    forbidden = ("ai.runtime.agent_runs.service",)
    violations = [module for module in _imports(registry) if module.startswith(forbidden)]
    assert violations == []


def test_interview_completion_uses_agent_run_submission_seam():
    """业务完成流程只依赖窄提交接口，不直接耦合队列 worker。"""
    path = BACKEND_AI / "workflows" / "interview" / "lifecycle" / "completion.py"
    modules = _imports(path)
    assert "ai.workflows.agent_runs.queue.submission" in modules
    assert not any(module.endswith(".queue.worker") for module in modules)


def test_agent_runs_api_uses_workflow_and_domain_not_runtime_service():
    """AgentRun HTTP 路由不应为任务类型常量直接依赖 runtime service。"""
    path = BACKEND_APP / "api" / "agent_runs.py"
    forbidden = ("ai.runtime.agent_runs.service",)
    violations = [module for module in _imports(path) if module.startswith(forbidden)]
    assert violations == []


def test_api_routes_do_not_depend_on_agents_or_infrastructure():
    """HTTP 路由只做传输适配，不直接耦合 agents/infrastructure 实现。"""
    violations: list[str] = []
    forbidden = ("ai.agents", "app.infrastructure", "integrations")
    for path in (BACKEND_APP / "api").rglob("*.py"):
        for module in _imports(path):
            if module.startswith(forbidden):
                violations.append(f"{path.relative_to(BACKEND_ROOT)} -> {module}")
    assert violations == []


def test_observability_init_only_reexports_pure_helper_modules():
    """纯配置、usage、provider 和汇总逻辑不得重新堆回 observability.__init__。"""

    package_root = BACKEND_ROOT / "observability"
    expected_modules = {
        "config.py",
        "langfuse_client.py",
        "providers.py",
        "summaries.py",
        "usage.py",
    }
    assert expected_modules <= {path.name for path in package_root.iterdir() if path.is_file()}

    tree = ast.parse((package_root / "__init__.py").read_text())
    top_level_names = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    moved_helpers = {
        "LangfuseConfig",
        "compare_governance_windows",
        "estimate_model_cost",
        "extract_token_usage",
        "infer_model_integration",
        "infer_model_provider",
        "measure_model_input",
        "provider_observability_metadata",
        "summarize_approval_events",
        "summarize_external_io_events",
        "summarize_governance_window",
        "summarize_model_events",
        "summarize_tool_events",
    }
    assert top_level_names.isdisjoint(moved_helpers)


def test_evaluation_repository_is_split_by_persistence_concern():
    """EvaluationRepository 聚合入口应保持轻量，具体持久化行为按关注点拆分。"""

    package_root = BACKEND_APP / "db" / "repositories" / "evaluation"
    expected_modules = {
        "annotation_repository.py",
        "dataset_repository.py",
        "gate_repository.py",
        "helpers.py",
        "run_repository.py",
    }
    assert expected_modules <= {path.name for path in package_root.iterdir() if path.is_file()}

    repository_path = package_root / "repository.py"
    tree = ast.parse(repository_path.read_text())
    repository_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "EvaluationRepository"
    )
    method_names = {
        node.name
        for node in repository_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert method_names == {"_case_model", "create_candidate_dataset_from_case_run"}
    assert len(repository_path.read_text().splitlines()) < 160


def test_workflows_root_contains_only_package_metadata():
    """具体 workflow 实现必须归属于显式业务域或组合子包。"""
    root_modules = {
        path.name
        for path in (BACKEND_AI / "workflows").iterdir()
        if path.is_file() and path.suffix == ".py" and path.name != "__init__.py"
    }
    assert root_modules == set()


def test_agents_and_tools_do_not_import_http_memory_workflow():
    """Agent/Tool 的 owner-scoped memory 能力不应依赖 HTTP 管理用例。"""
    violations: list[str] = []
    for root in (BACKEND_AI / "agents", BACKEND_AI / "tools"):
        for path in root.rglob("*.py"):
            for module in _imports(path):
                if module in {
                    "ai.workflows.memory",
                    "ai.workflows.memory.use_cases",
                }:
                    violations.append(f"{path.relative_to(BACKEND_ROOT)} -> {module}")
    assert violations == []


def test_workflow_domain_packages_have_explicit_init_modules():
    """Moved root-level workflow domains expose explicit package boundaries."""
    expected = {
        "applications",
        "configuration",
        "memory",
        "prompts",
        "agent_runs",
    }
    actual = {
        path.name
        for path in (BACKEND_AI / "workflows").iterdir()
        if path.is_dir() and (path / "__init__.py").exists()
    }
    assert expected <= actual

def test_workflow_internal_responsibility_modules_exist():
    """大型 workflow facade 的内部职责必须落在可独立测试的模块。"""
    expected_files = {
        BACKEND_AI / "workflows" / "agent_runs" / "events.py",
        BACKEND_AI / "workflows" / "agent_runs" / "queries.py",
        BACKEND_AI / "workflows" / "agent_runs" / "mutations.py",
        BACKEND_AI / "workflows" / "evaluation" / "run_filters.py",
        BACKEND_AI / "workflows" / "analysis" / "report_records.py",
        BACKEND_AI / "workflows" / "jobs" / "capture" / "context.py",
        BACKEND_AI / "workflows" / "jobs" / "capture" / "normalization.py",
        BACKEND_AI / "workflows" / "jobs" / "capture" / "scoring.py",
        BACKEND_AI / "workflows" / "interview" / "chat" / "events.py",
        BACKEND_AI / "workflows" / "interview" / "chat" / "memory.py",
    }
    assert all(path.is_file() for path in expected_files)


def test_workflow_facades_stay_below_large_module_threshold():
    """Facade 不得重新承载整个领域的实现细节。"""
    limits = {
        BACKEND_AI / "workflows" / "agent_runs" / "use_cases.py": 500,
        BACKEND_AI / "workflows" / "evaluation" / "runs.py": 550,
        BACKEND_AI / "workflows" / "analysis" / "analysis_service.py": 500,
        BACKEND_AI / "workflows" / "jobs" / "job_capture_service.py": 350,
        BACKEND_AI / "workflows" / "interview" / "chat" / "stream.py": 500,
    }
    violations = [
        f"{path.relative_to(BACKEND_ROOT)} has {len(path.read_text().splitlines())} lines"
        for path, limit in limits.items()
        if len(path.read_text().splitlines()) >= limit
    ]
    assert violations == []


def test_workflow_internal_helpers_do_not_import_their_facades():
    """纯辅助和内部协作者不能反向依赖同域 facade。"""
    forbidden_by_root = {
        BACKEND_AI / "workflows" / "agent_runs": (
            "ai.workflows.agent_runs.use_cases",
        ),
        BACKEND_AI / "workflows" / "analysis": (
            "ai.workflows.analysis.analysis_service",
        ),
        BACKEND_AI / "workflows" / "evaluation": (
            "ai.workflows.evaluation.service",
        ),
        BACKEND_AI / "workflows" / "jobs" / "capture": (
            "ai.workflows.jobs.job_capture_service",
            "ai.workflows.jobs.use_cases",
        ),
        BACKEND_AI / "workflows" / "interview" / "chat": (
            "ai.workflows.interview.chat.stream",
        ),
    }
    violations: list[str] = []
    for root, forbidden_modules in forbidden_by_root.items():
        for path in root.rglob("*.py"):
            for module in _imports(path):
                for forbidden in forbidden_modules:
                    if module == forbidden or module.startswith(f"{forbidden}."):
                        violations.append(f"{path.relative_to(BACKEND_ROOT)} -> {module}")
    assert violations == []
