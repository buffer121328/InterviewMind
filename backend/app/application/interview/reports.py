"""面试画像与短板地图用例。"""

from dataclasses import dataclass

from app.repositories.interview.weakness_report_repo import get_weakness_report_repo
from app.repositories.session.session_repo import SessionRepo
from app.schemas.schemas import ProfileGenerateRequest, WeaknessGenerateRequest
from app.services.analysis.ability_service import get_ability_service
from app.services.interview.interview_analysis import trigger_weakness_analysis


@dataclass(slots=True)
class InterviewReportUseCaseError(Exception):
    """面试报告用例异常。"""

    message: str


class InterviewReportBadRequest(InterviewReportUseCaseError):
    """面试报告请求不合法。"""


class InterviewReportNotFound(InterviewReportUseCaseError):
    """面试报告资源不存在或无权访问。"""


class InterviewReportUseCases:
    """面试画像和短板地图应用服务。"""

    def __init__(self) -> None:
        self._session_repo = SessionRepo()

    async def generate_profile(self, *, request: ProfileGenerateRequest | None, user_id: str) -> dict[str, object]:
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
        result = await get_ability_service().get_overall_profile(user_id=user_id)
        if result is None:
            return {"success": False, "message": "尚未生成综合能力画像。请点击「生成画像」按钮。"}
        return {"success": True, "profile": result["profile"], "generated_at": result["updated_at"]}

    async def get_session_profile(self, *, session_id: str, user_id: str) -> dict[str, object]:
        session = await self._session_repo.get_session(session_id, user_id=user_id)
        if not session:
            raise InterviewReportNotFound(message="会话不存在或无权访问")
        profile = await self._session_repo.get_profile(session_id)
        if profile is None:
            return {"success": False, "message": "画像生成中，请稍后刷新"}
        return {"success": True, "profile": profile}

    async def generate_weakness_report(self, *, request: WeaknessGenerateRequest, user_id: str) -> dict[str, object]:
        session_id = request.session_id
        if not session_id:
            raise InterviewReportBadRequest(message="session_id 不能为空")
        session = await self._session_repo.get_session(session_id, user_id=user_id)
        if not session:
            raise InterviewReportNotFound(message="会话不存在")

        api_config_dict = request.api_config.model_dump() if request.api_config else None
        await trigger_weakness_analysis(session_id, api_config_dict, user_id=user_id)
        report = await get_weakness_report_repo().get_report_by_session(session_id, user_id=user_id)
        if not report:
            return {"success": False, "message": "短板地图生成失败，请稍后重试"}
        return {"success": True, "message": "短板地图已生成", "report": report}

    async def get_weakness_by_session(self, *, session_id: str, user_id: str) -> dict[str, object]:
        report = await get_weakness_report_repo().get_report_by_session(session_id, user_id=user_id)
        if not report:
            return {"success": False, "message": "该会话暂无短板地图，请先生成"}
        return {"success": True, "report": report}

    async def get_weakness_history(self, *, user_id: str) -> dict[str, object]:
        reports = await get_weakness_report_repo().list_reports(user_id=user_id, limit=20)
        return {"success": True, "reports": reports}


interview_report_use_cases = InterviewReportUseCases()
