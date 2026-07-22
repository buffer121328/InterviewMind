"""队列载荷加密，确保 API Key、简历与 JD 不进入 Redis。"""

import json
import os

from cryptography.fernet import Fernet, InvalidToken


class TaskPayloadConfigurationError(RuntimeError):
    """队列加密配置缺失或密钥无效。"""


def _cipher() -> Fernet:
    """从环境变量获取加密密钥并构造 Fernet 密文器。"""
    key = os.getenv("TASK_PAYLOAD_ENCRYPTION_KEY")
    if not key:
        raise TaskPayloadConfigurationError("TASK_PAYLOAD_ENCRYPTION_KEY 未配置")
    try:
        return Fernet(key.encode())
    except (TypeError, ValueError) as exc:
        raise TaskPayloadConfigurationError("TASK_PAYLOAD_ENCRYPTION_KEY 无效") from exc


def encrypt_payload(payload: dict) -> str:
    """加密任务载荷（含 API Key 等敏感数据）。"""
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    return _cipher().encrypt(encoded).decode()


def decrypt_payload(payload_encrypted: str) -> dict:
    """解密任务载荷。"""
    try:
        decoded = _cipher().decrypt(payload_encrypted.encode())
        return json.loads(decoded.decode())
    except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TaskPayloadConfigurationError("任务载荷无法解密") from exc
