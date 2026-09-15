"""面试画像与短板地图用例。"""

import hashlib
import re
from dataclasses import dataclass

from ai.workflows.analysis.ability_service import get_ability_service
from app.db.repositories.interview.question_bank_repo import get_question_bank_repo
from app.db.repositories.interview.weakness_report_repo import get_weakness_report_repo
from app.db.repositories.session.session_repo import SessionRepo
from app.domain.ability_growth import (
    ability_profile_not_ready_message,
    build_ability_growth_record,
)
from app.domain.interview_reports import (
    build_interview_report_markdown,
    build_structured_interview_report,
)
from app.schemas.interview.interview_report import (
    SaveReportQuestionsRequest,
    SaveReportQuestionsResponse,
)
from app.schemas.interview.schemas import ProfileGenerateRequest
from app.schemas.interview.session import SessionMarkdownReportResponse


@dataclass(slots=True)
class InterviewReportUseCaseError(Exception):
    """面试报告用例异常。"""

    # 单条消息。
    # 单条消息。
    message: str


class InterviewReportNotFound(InterviewReportUseCaseError):
    """面试报告资源不存在或无权访问。"""


class InterviewReportBadRequest(InterviewReportUseCaseError):
    """面试报告训练交接请求不合法。"""


class InterviewReportUseCases:
    """面试画像和短板地图应用服务。"""

    def __init__(self) -> None:
        """初始化 `InterviewReportUseCases` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端只在后续方法调用时承担访问边界。"""
        self._session_repo = SessionRepo()
        self._question_bank_repo = get_question_bank_repo()

    async def generate_profile(self, *, request: ProfileGenerateRequest | None, user_id: str) -> dict[str, object]:
        """创建能力画像生成任务，并返回任务负载结果。

        Args:
            request: 请求对象。
            user_id: 用户 ID，所有者范围限定。
        """
        import uuid

        from ai.workflows.agent_runs.use_cases import agent_run_use_cases

        payload = request.model_dump(mode="json") if request else {}
        response = await agent_run_use_cases.create_ability_profile(
            payload=payload,
            user_id=user_id,
            idempotency_key=f"ability-profile:{user_id}:{uuid.uuid4()}",
        )
        return response.body

    async def get_overall_profile(self, *, user_id: str) -> dict[str, object]:
        """读取 overall profile，并通过 owner 校验限制可见范围；资源不存在或状态不合法时返回稳定的业务结果或异常。

        Args:
            user_id: 当前用户标识。
        """
        ability_service = get_ability_service()
        progress = await ability_service.get_profile_progress(user_id)
        result = await ability_service.get_overall_profile(user_id=user_id)
        if result is None:
            return {
                "success": False,
                "message": ability_profile_not_ready_message(progress),
                "sample_count": 0,
                "sources": [],
                "dimension_changes": {},
                "progress": progress,
            }
        sources = await self._session_repo.get_series_final_profile_records(limit=5, user_id=user_id)
        return build_ability_growth_record(
            overall=result,
            source_rows=sources,
            progress=progress,
        )

    async def get_session_report(
        self,
        *,
        session_id: str,
        user_id: str,
    ) -> SessionMarkdownReportResponse:
        """读取单场面试的统一 Markdown 报告（含画像与短板地图）。

        Args:
            session_id: 面试会话 ID。
            user_id: 用户 ID，所有者范围限定。
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
                status="not_ready",
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
        structured_profile, structured_weakness = build_structured_interview_report(profile, report)
        company_profile = session.metadata.company_profile
        if isinstance(company_profile, dict) and isinstance(company_profile.get("profile"), dict):
            combined = company_profile["profile"]
            markdown += "\n\n---\n\n# 公司三轮总画像\n\n"
            markdown += f"- 公司：{company_profile.get('company_info') or '未知公司'}\n"
            markdown += f"- 来源轮次：{len(company_profile.get('source_session_ids') or [])} 轮\n"
            markdown += f"- 综合评价：{combined.get('overall_assessment') or '暂无'}\n"
            strengths = combined.get("key_strengths") or []
            weaknesses = combined.get("key_weaknesses") or []
            if strengths:
                markdown += "\n## 跨轮优势\n" + "".join(f"- {item}\n" for item in strengths)
            if weaknesses:
                markdown += "\n## 跨轮改进项\n" + "".join(f"- {item}\n" for item in weaknesses)
        weakness_generation_mode = (
            structured_weakness.get("generation_mode")
            if isinstance(structured_weakness, dict)
            else getattr(structured_weakness, "generation_mode", "")
        )
        return SessionMarkdownReportResponse(
            success=True,
            session_id=session_id,
            status="degraded" if weakness_generation_mode == "degraded_evidence_only" else "ready",
            markdown=markdown,
            generated_at=generated_at or None,
            company_profile=company_profile,
            profile=structured_profile,
            weakness_report=structured_weakness,
        )

    async def save_recommended_questions(
        self,
        *,
        session_id: str,
        request: SaveReportQuestionsRequest,
        user_id: str,
    ) -> SaveReportQuestionsResponse:
        """把报告推荐题（按持久化索引）去重保存到题库。

        Args:
            session_id: 面试会话 ID。
            request: 请求对象。
            user_id: 用户 ID，所有者范围限定。
        """
        session = await self._session_repo.get_session(session_id, user_id=user_id)
        if not session:
            raise InterviewReportNotFound(message="会话不存在或无权访问")
        report = await get_weakness_report_repo().get_report_by_session(session_id, user_id=user_id)
        if report is None:
            raise InterviewReportBadRequest(message="本场面试报告尚未生成")
        report_data = report.get("report_data") if isinstance(report, dict) else None
        questions = list((report_data or {}).get("recommended_questions") or [])
        indices = list(dict.fromkeys(request.question_indices))
        if any(index < 0 or index >= len(questions) for index in indices):
            raise InterviewReportBadRequest(message="推荐题选择无效")
        item_ids: list[int] = []
        saved_count = 0
        for index in indices:
            question_text = str(questions[index]).strip()
            if not question_text:
                raise InterviewReportBadRequest(message="推荐题内容为空")
            normalized = re.sub(r"[\s？?。！!]+", "", question_text).casefold()
            source_id = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
            item_id, created = await self._question_bank_repo.create_report_question_if_absent(
                user_id=user_id, question_text=question_text, source_id=source_id,
                origin_session_id=session_id,
            )
            item_ids.append(item_id)
            saved_count += int(created)
        return SaveReportQuestionsResponse(
            saved_count=saved_count, skipped_count=len(item_ids) - saved_count, item_ids=item_ids
        )


interview_report_use_cases = InterviewReportUseCases()
