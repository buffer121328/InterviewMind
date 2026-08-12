"""评测工作流共享契约与稳定错误类型。"""

from dataclasses import dataclass
from typing import NoReturn


@dataclass(slots=True)
class EvaluationUseCaseError(Exception):
    """Evaluation 应用层稳定错误。"""

    message: str
    status_code: int = 400


def not_found(message: str) -> NoReturn:
    """抛出不会泄露资源是否属于其他用户的 404。"""
    raise EvaluationUseCaseError(message, status_code=404)
