"""提供载荷相关后端功能。"""

from __future__ import annotations

import json
import os

from cryptography.fernet import Fernet, InvalidToken


class TaskPayloadConfigurationError(RuntimeError):
    """定义任务载荷配置错误相关后端数据结构或服务组件。"""


def _cipher() -> Fernet:
    """处理加密器相关后端逻辑。"""

    key = os.getenv("TASK_PAYLOAD_ENCRYPTION_KEY")
    if not key:
        raise TaskPayloadConfigurationError("TASK_PAYLOAD_ENCRYPTION_KEY 未配置")
    try:
        return Fernet(key.encode())
    except (TypeError, ValueError) as exc:
        raise TaskPayloadConfigurationError("TASK_PAYLOAD_ENCRYPTION_KEY 无效") from exc


def encrypt_payload(payload: dict) -> str:
    """加密载荷相关后端逻辑。"""

    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    return _cipher().encrypt(encoded).decode()


def decrypt_payload(payload_encrypted: str) -> dict:
    """解密载荷相关后端逻辑。"""

    try:
        decoded = _cipher().decrypt(payload_encrypted.encode())
        return json.loads(decoded.decode())
    except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TaskPayloadConfigurationError("任务载荷无法解密") from exc
