"""模型凭据的 Fernet 加密封装。

与 `payload_crypto.py` 独立：模型凭据使用专属的 `MODEL_CREDENTIAL_ENCRYPTION_KEY`，
不得复用任务载荷密钥。密文格式为 ``v1:<fernet token>``，``v1`` 是密文格式版本；
轮换窗口内可用 ``MODEL_CREDENTIAL_ENCRYPTION_PREVIOUS_KEY`` 解密上一代密文。
"""

from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken

_CIPHERTEXT_PREFIX = "v1:"


class ModelCredentialCryptoError(RuntimeError):
    """模型凭据加密配置或解密失败。"""


class ModelCredentialCipher:
    """用当前密钥加密、按当前与上一代密钥依次解密。"""

    def __init__(self, current_key: str, previous_key: str = "") -> None:
        self._fernets = [self._build_fernet(current_key)]
        if previous_key.strip():
            self._fernets.append(self._build_fernet(previous_key.strip()))

    @staticmethod
    def _build_fernet(key: str) -> Fernet:
        try:
            return Fernet(key.encode())
        except (TypeError, ValueError) as exc:
            raise ModelCredentialCryptoError("模型凭据加密密钥无效") from exc

    def encrypt(self, secret: str) -> str:
        """加密敏感值并附加密文格式版本。"""

        token = self._fernets[0].encrypt(secret.encode()).decode()
        return f"{_CIPHERTEXT_PREFIX}{token}"

    def decrypt(self, envelope: str) -> str:
        """解密带版本前缀的密文，依次尝试当前与上一代密钥。"""

        if not isinstance(envelope, str) or not envelope.startswith(_CIPHERTEXT_PREFIX):
            raise ModelCredentialCryptoError("模型凭据密文格式无效")
        token = envelope[len(_CIPHERTEXT_PREFIX) :]
        for fernet in self._fernets:
            try:
                return fernet.decrypt(token.encode()).decode()
            except InvalidToken:
                continue
        raise ModelCredentialCryptoError("模型凭据无法解密：密钥不匹配或已轮换")


def build_model_credential_cipher() -> ModelCredentialCipher:
    """从环境变量构建凭据加密器；未配置当前密钥时 fail closed。"""

    current_key = os.getenv("MODEL_CREDENTIAL_ENCRYPTION_KEY", "").strip()
    if not current_key:
        raise ModelCredentialCryptoError("MODEL_CREDENTIAL_ENCRYPTION_KEY 未配置")
    previous_key = os.getenv("MODEL_CREDENTIAL_ENCRYPTION_PREVIOUS_KEY", "").strip()
    return ModelCredentialCipher(current_key, previous_key)
