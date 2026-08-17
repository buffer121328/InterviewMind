"""真实面试调试的安全配置预检工具。

脚本构造与前端一致的请求级模型通道配置：聊天、RAG Embedding 与 mem0
分别使用专用通道，且明文凭据只从环境变量或生产凭据存储按需水合。它不在
导入时建立数据库、Redis 或模型连接，适合在执行真实调试前先检查配置来源。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import uuid
from typing import Any

from ai.workflows.configuration.model_credentials import ModelCredentialUseCases
from app.schemas.schemas import ApiConfig
from app.security.model_credentials import get_model_credential_store

ROUND_TYPE = "hr_comprehensive"
MAX_QUESTIONS = 5
MODEL_NAME = os.getenv("INTERVIEW_MODEL", os.getenv("OPENAI_MODEL", "deepseek-v4-flash"))
MODEL_BASE_URL = os.getenv("INTERVIEW_BASE_URL", "https://api.deepseek.com/v1")
EMBEDDING_MODEL_NAME = os.getenv(
    "INTERVIEW_EMBEDDING_MODEL",
    os.getenv("EMBEDDING_MODEL", "text-embedding-v4"),
)
EMBEDDING_BASE_URL = os.getenv(
    "INTERVIEW_EMBEDDING_BASE_URL",
    os.getenv("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
)

RESUME_CONTEXT = """候选人：林舟（虚构）
目标岗位：高级后端/AI Agent 工程师
工作经历：5 年 Python、Java 后端经验，负责可恢复任务平台和 Agent 工作流。"""
JOB_DESCRIPTION = "高级 AI Agent 后端工程师，负责可恢复、可观测、可评测的 Agent 工作流。"
COMPANY_INFO = "虚构调试公司"


def _provider_for(*, model: str, base_url: str) -> str | None:
    """为调试输出和请求元数据推断已知供应商，不影响凭据选择。"""

    normalized_url = base_url.lower()
    if model.startswith("deepseek") or "api.deepseek.com" in normalized_url:
        return "deepseek"
    if "dashscope.aliyuncs.com" in normalized_url:
        return "aliyun"
    if "api.openai.com" in normalized_url:
        return "openai"
    return None


def _model_channel(*, model: str, base_url: str) -> dict[str, str | None]:
    """构造不含明文密钥、可由生产凭据用例水合的模型通道。"""

    return {
        "credential_id": "",
        "api_key": "",
        "base_url": base_url,
        "model": model,
        "provider": _provider_for(model=model, base_url=base_url),
    }


def credential_reference_config() -> dict[str, dict[str, str | None]]:
    """构造与前端相同的聊天、RAG 和 mem0 无明文模型引用。"""

    chat_channel = _model_channel(model=MODEL_NAME, base_url=MODEL_BASE_URL)
    embedding_channel = _model_channel(
        model=EMBEDDING_MODEL_NAME,
        base_url=EMBEDDING_BASE_URL,
    )
    return {
        "smart": dict(chat_channel),
        "fast": dict(chat_channel),
        "rag_embedding": dict(embedding_channel),
        "mem0_llm": dict(chat_channel),
        "mem0_embedder": dict(embedding_channel),
    }


def _explicit_chat_api_key() -> str:
    """读取聊天专用环境凭据，避免把 Embedding Key 发到聊天网关。"""

    explicit = os.getenv("INTERVIEW_API_KEY") or os.getenv("MEM0_LLM_API_KEY")
    if explicit:
        return explicit
    provider = _provider_for(model=MODEL_NAME, base_url=MODEL_BASE_URL)
    if provider == "deepseek":
        return os.getenv("DEEPSEEK_API_KEY", "")
    if provider == "aliyun":
        return os.getenv("DASHSCOPE_API_KEY", "")
    if provider == "openai":
        return os.getenv("OPENAI_API_KEY", "")
    return ""


def _explicit_embedding_api_key() -> str:
    """读取 Embedding 专用环境凭据，不复用聊天模型的供应商假设。"""

    explicit = os.getenv("INTERVIEW_EMBEDDING_API_KEY") or os.getenv("MEM0_EMBEDDER_API_KEY")
    if explicit:
        return explicit
    provider = _provider_for(model=EMBEDDING_MODEL_NAME, base_url=EMBEDDING_BASE_URL)
    if provider == "aliyun":
        return os.getenv("DASHSCOPE_API_KEY", "")
    if provider == "openai":
        return os.getenv("OPENAI_API_KEY", "")
    return ""


async def hydrate_api_config(user_id: str) -> ApiConfig:
    """按通道复用生产凭据用例水合配置，不直接读取 Redis key。"""

    payload: dict[str, Any] = {"api_config": credential_reference_config()}
    api_config = payload["api_config"]
    sources: list[str] = []

    chat_key = _explicit_chat_api_key()
    if chat_key:
        for channel in ("smart", "fast", "mem0_llm"):
            api_config[channel]["api_key"] = chat_key
        sources.append("environment")

    embedding_key = _explicit_embedding_api_key()
    if embedding_key:
        for channel in ("rag_embedding", "mem0_embedder"):
            api_config[channel]["api_key"] = embedding_key
        sources.append("environment")

    missing_channels = frozenset(
        channel
        for channel, channel_config in api_config.items()
        if not channel_config.get("api_key")
    )
    if missing_channels:
        use_cases = ModelCredentialUseCases(get_model_credential_store())
        await use_cases.hydrate_request(
            payload,
            user_id,
            allowed_channels=missing_channels,
        )
        sources.append("production credential store")

    config = ApiConfig.model_validate(api_config)
    source = " + ".join(sources) or "production credential store"
    print(
        "[模型配置] "
        f"chat={MODEL_NAME} @ {MODEL_BASE_URL}; "
        f"embedding={EMBEDDING_MODEL_NAME} @ {EMBEDDING_BASE_URL}"
        f"（凭据来源：{source}，不输出明文）"
    )
    return config


def build_start_payload(thread_id: str, api_config: ApiConfig) -> dict[str, Any]:
    """构造生产 interview_start payload；业务素材均为虚构调试数据。"""

    return {
        "thread_id": thread_id,
        "mode": "mock",
        "resume_filename": "debug_candidate_resume.md",
        "resume_context": RESUME_CONTEXT,
        "job_description": JOB_DESCRIPTION,
        "company_info": COMPANY_INFO,
        "round_type": ROUND_TYPE,
        "max_questions": MAX_QUESTIONS,
        "question_bank_count": 0,
        "experience_questions": [],
        "api_config": api_config.model_dump(),
    }


def _parser() -> argparse.ArgumentParser:
    """构建调试预检命令行参数。"""

    parser = argparse.ArgumentParser(description="真实面试调试配置预检")
    parser.add_argument(
        "--user-id",
        default=f"debug-real-user-{uuid.uuid4().hex[:10]}",
        help="用于从生产凭据存储解析模型密钥的用户标识",
    )
    return parser


async def main() -> None:
    """水合并验证真实调试所需的请求级模型配置。"""

    args = _parser().parse_args()
    config = await hydrate_api_config(args.user_id)
    payload = build_start_payload(f"debug-real-session-{uuid.uuid4().hex[:10]}", config)
    print(
        "[预检通过] "
        f"round_type={payload['round_type']} max_questions={payload['max_questions']} "
        "；未输出任何 API Key。"
    )


if __name__ == "__main__":
    asyncio.run(main())
