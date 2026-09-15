"""真实面试调试的安全配置预检工具。

脚本构造与前端一致的请求级模型通道配置：聊天、RAG Embedding 与 mem0
分别使用专用通道，且 API Key 只从生产 Redis 凭据存储按需水合。它不在导入时
建立数据库、Redis 或模型连接，适合在执行真实调试前先检查配置来源。
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from typing import Any

from ai.workflows.configuration.model_credentials import ModelCredentialUseCases
from app.schemas.schemas import ApiConfig
from app.security.model_credentials import get_model_credential_store

ROUND_TYPE = "hr_comprehensive"
MAX_QUESTIONS = 5
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


def _model_channel(*, model: str, base_url: str, dimensions: int | None = None) -> dict[str, str | int | None]:
    """构造不含明文密钥、可由生产凭据用例水合的模型通道。"""

    channel: dict[str, str | int | None] = {
        "credential_id": "",
        "api_key": "",
        "base_url": base_url,
        "model": model,
        "provider": _provider_for(model=model, base_url=base_url),
    }
    if dimensions is not None:
        channel["dimensions"] = dimensions
    return channel


def credential_reference_config(
    *,
    chat_model: str,
    chat_base_url: str,
    embedding_model: str,
    embedding_base_url: str,
    embedding_dimensions: int,
) -> dict[str, dict[str, str | int | None]]:
    """构造与前端相同的聊天、RAG 和 mem0 无明文模型引用。"""

    chat_channel = _model_channel(model=chat_model, base_url=chat_base_url)
    embedding_channel = _model_channel(
        model=embedding_model,
        base_url=embedding_base_url,
        dimensions=embedding_dimensions,
    )
    return {
        "smart": dict(chat_channel),
        "fast": dict(chat_channel),
        "rag_embedding": dict(embedding_channel),
        "mem0_llm": dict(chat_channel),
        "mem0_embedder": dict(embedding_channel),
    }


async def hydrate_api_config(
    user_id: str,
    *,
    chat_model: str,
    chat_base_url: str,
    embedding_model: str,
    embedding_base_url: str,
    embedding_dimensions: int,
) -> ApiConfig:
    """按通道复用生产凭据用例水合配置，不直接读取 Redis key。"""

    payload: dict[str, Any] = {
        "api_config": credential_reference_config(
            chat_model=chat_model,
            chat_base_url=chat_base_url,
            embedding_model=embedding_model,
            embedding_base_url=embedding_base_url,
            embedding_dimensions=embedding_dimensions,
        )
    }
    api_config = payload["api_config"]
    use_cases = ModelCredentialUseCases(get_model_credential_store())
    await use_cases.hydrate_request(
        payload,
        user_id,
        allowed_channels=frozenset(api_config),
    )

    config = ApiConfig.model_validate(api_config)
    print(
        "[模型配置] "
        f"chat={chat_model} @ {chat_base_url}; "
        f"embedding={embedding_model} @ {embedding_base_url}"
        "（凭据来源：Redis owner 密文存储，不输出明文）"
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
    parser.add_argument("--chat-model", required=True, help="前端已保存的聊天技术模型名")
    parser.add_argument("--chat-base-url", required=True, help="前端已保存的聊天 Base URL")
    parser.add_argument("--embedding-model", required=True, help="前端已保存的 Embedding 技术模型名")
    parser.add_argument("--embedding-base-url", required=True, help="前端已保存的 Embedding Base URL")
    parser.add_argument("--embedding-dimensions", type=int, required=True, help="前端已保存的 Embedding 输出维度")
    return parser


async def main() -> None:
    """水合并验证真实调试所需的请求级模型配置。"""

    args = _parser().parse_args()
    config = await hydrate_api_config(
        args.user_id,
        chat_model=args.chat_model,
        chat_base_url=args.chat_base_url,
        embedding_model=args.embedding_model,
        embedding_base_url=args.embedding_base_url,
        embedding_dimensions=args.embedding_dimensions,
    )
    payload = build_start_payload(f"debug-real-session-{uuid.uuid4().hex[:10]}", config)
    print(
        "[预检通过] "
        f"round_type={payload['round_type']} max_questions={payload['max_questions']} "
        "；未输出任何 API Key。"
    )


if __name__ == "__main__":
    asyncio.run(main())
