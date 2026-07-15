"""队列载荷加密，确保 API Key、简历与 JD 不进入 Redis。"""

import json
import os

from cryptography.fernet import Fernet, InvalidToken


class TaskPayloadConfigurationError(RuntimeError):
    pass


def _cipher() -> Fernet:
    key = os.getenv("TASK_PAYLOAD_ENCRYPTION_KEY")
    if not key:
        raise TaskPayloadConfigurationError("TASK_PAYLOAD_ENCRYPTION_KEY 未配置")
    try:
        return Fernet(key.encode())
    except (TypeError, ValueError) as exc:
        raise TaskPayloadConfigurationError("TASK_PAYLOAD_ENCRYPTION_KEY 无效") from exc


def encrypt_payload(payload: dict) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    return _cipher().encrypt(encoded).decode()


def decrypt_payload(payload_encrypted: str) -> dict:
    try:
        decoded = _cipher().decrypt(payload_encrypted.encode())
        return json.loads(decoded.decode())
    except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TaskPayloadConfigurationError("任务载荷无法解密") from exc
