"""
FastAPI 主入口文件
AI 面试助手后端服务
"""

import asyncio
import logging
import os
import signal
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import (
    agent_runs,
    applications,
    artifacts,
    config,
    langfuse_prompts,
)
from app.api.evaluation import router as evaluation_router
from app.api.interview import router as interview_router
from app.api.interview_experience import router as interview_experience_router
from app.api.jobs import router as jobs_router
from app.api.memory import router as memory_router
from app.api.question_bank import router as question_bank_router
from app.api.resume import router as resume_router
from app.api.resume import upload_router
from app.config import get_settings
from app.runtime_paths import ensure_runtime_directories
from app.security.config_validate_guard import ConfigValidateGuardMiddleware
from app.security.model_credential_middleware import ModelCredentialHydrationMiddleware
from app.security.security import redact_secrets, safe_error_message

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理
    """
    # 启动时执行
    logger.info("AI 面试助手后端服务启动中...")

    from ai.workflows.agent_runs.catalog import validate_production_catalog

    validate_production_catalog()
    logger.info("✓ Agent Harness Catalog 一致性校验通过")

    from observability import configure_langfuse
    if configure_langfuse():
        logger.info("Langfuse Agent 观测已启用")

    # 本地开发可自动同步 ORM 表结构；严格迁移验证时设 AUTO_CREATE_TABLES=false。
    settings = get_settings()
    if settings.auto_create_tables:
        from app.db.models import init_db
        await init_db()
    else:
        logger.info("AUTO_CREATE_TABLES=false，跳过 ORM 表结构自动同步，请确保已执行 Alembic 迁移")
        from app.db.models import engine
        from app.db.rag_schema import validate_rag_vector_schema

        await validate_rag_vector_schema(engine)
        logger.info("✓ RAG pgvector 列维度预检通过")

    ensure_runtime_directories(settings.runtime_paths)
    logger.info("后端运行目录初始化完成")

    # 主动恢复 Worker 中断或长期未领取的持久化 Agent 任务
    try:
        from ai.runtime.execution.background import create_background_task
        from ai.workflows.agent_runs.queue.recovery import run_agent_run_recovery_loop
        create_background_task(run_agent_run_recovery_loop(), name="agent-run-recovery")
    except Exception as e:
        logger.warning("Agent 任务主动恢复循环启动失败: %s", e)

    # mem0 模型连接来自前端请求并由 Redis owner 凭据水合，不能在启动时预初始化。
    logger.info("mem0 使用请求级模型配置与 Redis 凭据，首次记忆请求时按需初始化")

    yield   # 暂停点，应用开始运行

    # 关闭时执行
    logger.info("AI 面试助手后端服务关闭中...")

    # 清理资源
    await cleanup_resources()

async def cleanup_resources():
    """
    清理所有资源，including数据库连接和图实例
    """
    logger.info("正在清理资源...")

    try:
        from observability import shutdown_langfuse
        shutdown_langfuse()
        logger.info("Langfuse 观测客户端已关闭")
    except Exception as e:
        logger.error(f"关闭 Langfuse 观测客户端时出错: {e}")

    # 等待/取消应用级后台任务
    try:
        from ai.runtime.execution.background import drain_background_tasks
        await drain_background_tasks(timeout=5.0)
        logger.info("✓ 后台任务已清理")
    except Exception as e:
        logger.error(f"✗ 清理后台任务时出错: {e}")

    # 关闭全局 checkpointer 和连接
    try:
        from ai.memory.memory import close_checkpointer
        await close_checkpointer()
        logger.info("✓ Checkpointer 已关闭")
    except Exception as e:
        logger.error(f"✗ 关闭 checkpointer 时出错: {e}")

    # 关闭 mem0 长期记忆服务
    try:
        from ai.memory import close_agent_memory_service
        await close_agent_memory_service()
        logger.info("✓ AgentMemoryService 已关闭")
    except Exception as e:
        logger.error(f"✗ 关闭 AgentMemoryService 时出错: {e}")

    # 清理图实例列表
    try:
        from ai.agents.interview.interview_graph import clear_graph_instances
        clear_graph_instances()
        logger.info("✓ 图实例列表已清空")
    except Exception as e:
        logger.error(f"✗ 清理图实例时出错: {e}")

    # 关闭 SQLAlchemy 引擎
    try:
        from app.db.models import engine
        await engine.dispose()
        logger.info("✓ SQLAlchemy 引擎已关闭")
    except Exception as e:
        logger.error(f"✗ 关闭 SQLAlchemy 引擎时出错: {e}")

    logger.info("资源清理完成")

def handle_signal(signum, frame):
    """
    处理系统信号，实现优雅关闭
    """
    logger.info(f"接收到信号 {signum}，开始关闭...")

    # 使用线程池来执行异步清理
    import threading

    def run_cleanup():
        """在新线程中运行清理函数"""
        loop: asyncio.AbstractEventLoop | None = None
        try:
            # 创建新的事件循环
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # 运行清理函数
            loop.run_until_complete(cleanup_resources())
            logger.info("资源清理完成")

        except Exception as e:
            logger.error(f"清理资源时出错: {e}")
        finally:
            if loop is not None:
                try:
                    loop.close()
                except Exception:
                    logger.debug("关闭清理事件循环时出错", exc_info=True)

    # 启动清理线程
    cleanup_thread = threading.Thread(target=run_cleanup)
    cleanup_thread.start()

    # 等待清理线程完成（最多等待3秒）
    cleanup_thread.join(timeout=3)

    # 退出程序
    sys.exit(0)


# 创建 FastAPI 应用实例
app = FastAPI(
    title="AI 面试助手 API",
    description="基于 FastAPI + LangGraph 的智能面试系统后端",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)


# 凭据解析位于业务路由之前；CORS 后注册使其保持最外层并覆盖凭据错误响应。
app.add_middleware(ModelCredentialHydrationMiddleware)

# 配置验证端点的输入边界（大小/频率/并发），在业务路由前生效。
app.add_middleware(ConfigValidateGuardMiddleware)

# 配置 CORS - 允许的前端域名
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",                         # 本地开发
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 全局异常处理器
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """HTTP 异常处理"""
    if exc.status_code >= 500:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": "InternalServerError", "message": "服务器内部错误，请稍后重试"},
        )
    return JSONResponse(
        status_code=exc.status_code,
        content=redact_secrets(exc.detail) if isinstance(exc.detail, dict) else {
            "error": "HTTPException",
            "message": redact_secrets(exc.detail)
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """通用异常处理"""
    logger.error(f"未处理的异常: {safe_error_message(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "InternalServerError",
            "message": "服务器内部错误,请稍后重试"
        }
    )


# 根路径
@app.get("/")
async def root():
    """
    根路径，返回 API 信息
    """
    return {
        "message": "AI 面试助手 API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/api/docs",
        "redoc": "/api/redoc"
    }


# 健康检查
@app.get("/health")
async def health_check():
    """处理健康检查相关后端逻辑。"""
    from ai.memory.service import get_agent_memory_runtime_status

    return {
        "status": "healthy",
        "message": "服务运行正常",
        "services": {
            "mem0": get_agent_memory_runtime_status(),
        },
    }


# 注册路由
app.include_router(interview_router)
app.include_router(agent_runs.router)
app.include_router(upload_router)
app.include_router(config.router)
app.include_router(resume_router)
app.include_router(applications.router)
app.include_router(question_bank_router)
app.include_router(memory_router)
app.include_router(jobs_router)
app.include_router(interview_experience_router)
app.include_router(langfuse_prompts.router)
app.include_router(artifacts.router)
app.include_router(evaluation_router)

# URL 保持 /static；磁盘目录由 cwd-independent runtime settings 决定。
app.mount(
    "/static",
    StaticFiles(directory=str(get_settings().static_storage_path), check_dir=False),
    name="static",
)


# 启动信息
if __name__ == "__main__":
    import uvicorn

    # 注册信号处理器，当收到关闭信号时（Ctrl+C 或 kill），执行 handle_signal 函数实现优雅关闭
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # 从环境变量读取配置，如果没有则使用默认值
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    debug = os.getenv("DEBUG", "false").lower() == "true"

    logger.info(f"启动服务器: http://{host}:{port}")
    logger.info(f"API 文档: http://{host}:{port}/api/docs")
    logger.info("按 Ctrl+C 可以正常关闭服务器")

    try:
        # uvicorn 是一个 ASGI 服务器，用来运行 FastAPI 应用
        uvicorn.run(
            "app.main:app",
            host=host,
            port=port,
            reload=debug,
            log_level="info"
        )
    except KeyboardInterrupt:
        logger.info("接收到键盘中断，正在关闭...")
    except Exception as e:
        logger.error(f"服务器运行出错: {e}")
    finally:
        logger.info("服务器已关闭")
