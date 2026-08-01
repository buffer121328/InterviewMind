"""岗位自动化应用用例包。

顶层统一组装与 re-export；实现位于 use_cases 与各领域服务子模块。
"""

from .use_cases import (
    JobBadRequest,
    JobBrowserTabUnavailable,
    JobNotFound,
    JobsUseCaseError,
    JobsUseCases,
    jobs_use_cases,
)

__all__ = [
    "JobBadRequest",
    "JobBrowserTabUnavailable",
    "JobNotFound",
    "JobsUseCaseError",
    "JobsUseCases",
    "jobs_use_cases",
]
