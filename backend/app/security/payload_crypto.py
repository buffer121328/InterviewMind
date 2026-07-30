"""Fernet JSON payload encryption shared by persistence and AgentRun layers."""

from __future__ import annotations

import json
import os

from cryptography.fernet import Fernet, InvalidToken


class TaskPayloadConfigurationError(RuntimeError):
    """Payload encryption configuration is missing or invalid."""


def _cipher() -> Fernet:
    """Build the Fernet cipher from the declared task payload key."""

    key = os.getenv("TASK_PAYLOAD_ENCRYPTION_KEY")
    if not key:
        raise TaskPayloadConfigurationError("TASK_PAYLOAD_ENCRYPTION_KEY 未配置")
    try:
        return Fernet(key.encode())
    except (TypeError, ValueError) as exc:
        raise TaskPayloadConfigurationError("TASK_PAYLOAD_ENCRYPTION_KEY 无效") from exc


def encrypt_payload(payload: dict) -> str:
    """Encrypt a JSON payload that may contain sensitive business data."""

    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    return _cipher().encrypt(encoded).decode()


def decrypt_payload(payload_encrypted: str) -> dict:
    """Decrypt and validate one encrypted JSON payload."""

    try:
        decoded = _cipher().decrypt(payload_encrypted.encode())
        return json.loads(decoded.decode())
    except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TaskPayloadConfigurationError("任务载荷无法解密") from exc
