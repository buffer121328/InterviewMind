"""面试画像与短板地图用例。"""

from dataclasses import dataclass

from app.domain.interview_reports import build_interview_report_markdown
from app.db.repositories.interview.weakness_report_repo import get_weakness_report_repo
from app.db.repositories.session.session_repo import SessionRepo
from app.schemas.session import SessionMarkdownReportResponse
from app.schemas.schemas import ProfileGenerateRequest
from ai.workflows.analysis.ability_service import get_ability_service


@dataclass(slots=True)
class InterviewReportUseCaseError(Exception):
    """面试报告用例异常。"""

    message: str


class InterviewReportNotFound(InterviewReportUseCaseError):
    """面试报告资源不存在或无权访问。"""


class InterviewReportUseCases:
    """面试画像和短板地图应用服务。"""

    def __init__(self) -> None:
        """初始化 `InterviewReportUseCases` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端只在后续方法调用时承担访问边界。"""
        self._session_repo = SessionRepo()

    async def generate_profile(self, *, request: ProfileGenerateRequest | None, user_id: str) -> dict[str, object]:
        """基于已完成面试内容生成能力画像，并把模型结果限制在当前用户和脱敏后的观测范围内。

        Args:
            request: 请求对象。
            user_id: 当前用户标识。
        """
        api_config_dict = request.api_config.model_dump() if (request and request.api_config) else None
        try:
            result = await get_ability_service().generate_overall_profile(user_id=user_id, api_config=api_config_dict)
        except ValueError as exc:
            return {"success": False, "message": str(exc)}

        profile = result["profile"]
        warning = result.get("warning")
        if profile.overall_assessment == "暂无面试记录，请先进行模拟面试。":
            return {"success": False, "message": "暂无面试记录，无法生成画像。请先完成至少一次模拟面试。"}

        response = {"success": True, "message": "综合能力画像已生成", "profile": profile.model_dump()}
        if warning:
            response["warning"] = warning
        return response

    async def get_overall_profile(self, *, user_id: str) -> dict[str, object]:
        """读取 overall profile，并通过 owner 校验限制可见范围；资源不存在或状态不合法时返回稳定的业务结果或异常。

        Args:
            user_id: 当前用户标识。
        """
        result = await get_ability_service().get_overall_profile(user_id=user_id)
        if result is None:
            return {"success": False, "message": "尚未生成综合能力画像。请点击「生成画像」按钮。"}
        return {"success": True, "profile": result["profile"], "generated_at": result["updated_at"]}

    async def get_session_report(
        self,
        *,
        session_id: str,
        user_id: str,
    ) -> SessionMarkdownReportResponse:
        """Return one owner-scoped Markdown report assembled from both persisted artifacts.

        The endpoint deliberately exposes neither the resume snapshot nor raw model
        payloads. A report becomes downloadable only after both parts of the single
        report-generation task have been persisted.
        """
        session = await self._session_repo.get_session(session_id, user_id=user_id)
        if not session:
            raise InterviewReportNotFound(message="会话不存在或无权访问")
        profile = await self._session_repo.get_profile(session_id, user_id=user_id)
        report = await get_weakness_report_repo().get_report_by_session(session_id, user_id=user_id)
        if profile is None or report is None:
            return SessionMarkdownReportResponse(
                success=False,
                session_id=session_id,
                message="本场面试报告尚未生成或仍在生成中",
            )
        generated_at = str(report.get("updated_at") or profile.get("last_updated") or "")
        markdown = build_interview_report_markdown(
            title=session.title,
            mode=session.metadata.mode,
            round_index=session.metadata.round_index,
            max_questions=session.metadata.max_questions,
            profile=profile,
            weakness_report=report,
            generated_at=generated_at,
        )
        return SessionMarkdownReportResponse(
            success=True,
            session_id=session_id,
            markdown=markdown,
            generated_at=generated_at or None,
        )

interview_report_use_cases = InterviewReportUseCases()
