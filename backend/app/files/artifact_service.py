"""Private HTML/PDF report exports stored on a Docker-mounted persistent volume."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
from sqlalchemy import select

from app.db.models import (
    AgentRunModel,
    ArtifactModel,
    JdAnalysisResultModel,
    ResumeResultModel,
    SessionModel,
    WeaknessReportModel,
    GeneratedResumeModel,
    async_session,
)
from app.domain.interview_reports import build_interview_report_markdown
from app.schemas.artifacts import ArtifactExportRequest

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_MIME = {"html": "text/html; charset=utf-8", "pdf": "application/pdf"}


class ArtifactNotFound(Exception):
    """Raised when an export source or artifact is unavailable to the current owner."""


class ArtifactService:
    """Render owner-scoped persisted reports to private files and serve them only after DB checks."""

    def __init__(self, storage_dir: str | None = None) -> None:
        """Use the configured volume directory, never the publicly mounted static directory."""
        self._root = Path(storage_dir or os.getenv("ARTIFACT_STORAGE_DIR", "/app/data/artifacts")).resolve()

    @staticmethod
    def _now() -> datetime:
        """Return a shared timestamp for metadata writes."""
        return datetime.now()

    @staticmethod
    def _safe_filename(title: str, extension: str) -> str:
        """Create a bounded download name without path separators or unsafe Unicode control characters."""
        stem = _SAFE_NAME.sub("-", title).strip(".-")[:100] or "report"
        return f"{stem}.{extension}"

    async def _source(self, request: ArtifactExportRequest, user_id: str) -> tuple[str, dict[str, Any], str | None]:
        """Read one report source under owner filtering and return title, display-safe data and optional run link."""
        async with async_session() as session:
            if request.source_type == "generated_resume":
                row = await session.scalar(select(GeneratedResumeModel).where(GeneratedResumeModel.id == int(request.source_id), GeneratedResumeModel.user_id == user_id))
                if row:
                    return row.title, {"最终简历": row.content, "目标岗位": row.job_description or ""}, row.agent_run_id
            elif request.source_type == "agent_run":
                row = await session.scalar(select(AgentRunModel).where(AgentRunModel.id == request.source_id, AgentRunModel.user_id == user_id))
                if row:
                    return row.task_type, {"任务类型": row.task_type, "状态": row.status, "结果": row.result or {}, "步骤": row.step_results or {}}, row.id
            elif request.source_type == "resume_result":
                row = await session.scalar(select(ResumeResultModel).where(ResumeResultModel.id == int(request.source_id), ResumeResultModel.user_id == user_id))
                if row:
                    return f"简历{row.result_type}报告", row.result_data, row.agent_run_id
            elif request.source_type == "jd_analysis":
                row = await session.scalar(select(JdAnalysisResultModel).where(JdAnalysisResultModel.id == int(request.source_id), JdAnalysisResultModel.user_id == user_id))
                if row:
                    return "JD 匹配报告", row.analysis_result, None
            elif request.source_type == "weakness_report":
                row = await session.scalar(select(WeaknessReportModel).where(WeaknessReportModel.id == int(request.source_id), WeaknessReportModel.user_id == user_id))
                if row:
                    return "面试复盘报告", row.report_data, None
            elif request.source_type == "interview_report":
                interview = await session.scalar(
                    select(SessionModel).where(
                        SessionModel.session_id == request.source_id,
                        SessionModel.user_id == user_id,
                    )
                )
                weakness = await session.scalar(
                    select(WeaknessReportModel).where(
                        WeaknessReportModel.session_id == request.source_id,
                        WeaknessReportModel.user_id == user_id,
                    )
                )
                if interview and interview.candidate_profile and weakness:
                    markdown = build_interview_report_markdown(
                        title=interview.title,
                        mode=interview.mode,
                        round_index=interview.round_index,
                        max_questions=interview.max_questions,
                        profile=interview.candidate_profile,
                        weakness_report=weakness.report_data,
                        generated_at=weakness.updated_at.isoformat(),
                    )
                    return f"{interview.title}-面试报告", {"markdown": markdown}, None
        raise ArtifactNotFound()

    @staticmethod
    def _inline_markdown_html(text: str) -> str:
        """Escape resume text first, then apply the small inline subset used by generated resumes."""
        escaped = html.escape(text)
        escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
        escaped = re.sub(r"`(.+?)`", r"<code>\1</code>", escaped)
        return escaped

    @classmethod
    def _markdown_html(cls, markdown: str) -> str:
        """Render a safe resume-oriented Markdown subset without accepting raw HTML."""
        parts: list[str] = []
        paragraph: list[str] = []
        list_kind: str | None = None

        def flush_paragraph() -> None:
            if paragraph:
                parts.append(f"<p>{'<br>'.join(cls._inline_markdown_html(line) for line in paragraph)}</p>")
                paragraph.clear()

        def close_list() -> None:
            nonlocal list_kind
            if list_kind:
                parts.append(f"</{list_kind}>")
                list_kind = None

        for raw_line in markdown.replace("\r\n", "\n").split("\n"):
            line = raw_line.strip()
            if not line:
                flush_paragraph()
                close_list()
                continue
            heading = re.match(r"^(#{1,3})\s+(.+)$", line)
            if heading:
                flush_paragraph()
                close_list()
                level = len(heading.group(1))
                parts.append(f"<h{level}>{cls._inline_markdown_html(heading.group(2))}</h{level}>")
                continue
            bullet = re.match(r"^[-*+]\s+(.+)$", line)
            numbered = re.match(r"^\d+[.)]\s+(.+)$", line)
            if bullet or numbered:
                flush_paragraph()
                next_kind = "ul" if bullet else "ol"
                if list_kind != next_kind:
                    close_list()
                    parts.append(f"<{next_kind}>")
                    list_kind = next_kind
                item = bullet.group(1) if bullet else numbered.group(1)
                parts.append(f"<li>{cls._inline_markdown_html(item)}</li>")
                continue
            close_list()
            paragraph.append(line)

        flush_paragraph()
        close_list()
        return "".join(parts)

    @staticmethod
    def _resume_styles() -> str:
        """Return the shared professional color and A4 layout used by HTML exports."""
        return """
        :root{--ink:#172033;--muted:#526173;--teal:#0f766e;--teal-dark:#164e63;--teal-soft:#ecfdf5;--line:#cbd5e1}
        *{box-sizing:border-box}html,body{margin:0;padding:0;background:#e8eef1;color:var(--ink)}
        body{font-family:"Avenir Next","Segoe UI","Microsoft YaHei",Arial,sans-serif;font-size:11pt;line-height:1.52}
        .resume-sheet{position:relative;width:210mm;min-height:297mm;margin:12mm auto;padding:17mm 17mm 16mm;background:#fff;box-shadow:0 14px 42px rgba(15,23,42,.14);overflow:hidden}
        .resume-sheet:before{content:"";position:absolute;inset:0 0 auto;height:7mm;background:linear-gradient(90deg,var(--teal-dark),var(--teal),#14b8a6)}
        .resume-content h1{margin:4mm 0 2mm;color:var(--teal-dark);font-size:25pt;line-height:1.08;letter-spacing:-.03em;text-align:center}
        .resume-content h1+p{margin-bottom:5mm;text-align:center;color:var(--muted)}
        .resume-content h2{margin:6mm 0 2.5mm;padding:1.8mm 3mm;color:#fff;background:linear-gradient(90deg,var(--teal-dark),var(--teal));border-radius:1.6mm;font-size:11.5pt;line-height:1.2;letter-spacing:.08em;break-after:avoid}
        .resume-content h3{margin:3.5mm 0 1mm;padding-left:2.5mm;border-left:1.2mm solid #14b8a6;color:var(--ink);font-size:11pt;break-after:avoid}
        .resume-content p{margin:0 0 1.8mm;color:var(--muted)}
        .resume-content ul,.resume-content ol{margin:1mm 0 2.5mm;padding-left:5.5mm}
        .resume-content li{margin:0 0 1.2mm;color:#334155;padding-left:.5mm}
        .resume-content strong{color:var(--ink);font-weight:700}.resume-content code{padding:.2mm 1mm;border-radius:1mm;background:var(--teal-soft);color:var(--teal-dark)}
        h1,h2,h3,p,li{orphans:3;widows:3}.export-meta{margin:0 0 4mm;text-align:right;color:#94a3b8;font-size:8pt}
        @page{size:A4;margin:0}@media print{html,body{background:#fff}.resume-sheet{margin:0;box-shadow:none}.resume-content ul,.resume-content ol{break-inside:avoid}}
        """

    @classmethod
    def _resume_html_document(cls, title: str, markdown: str) -> str:
        """Render generated resume Markdown as a styled standalone A4 document."""
        body = cls._markdown_html(markdown)
        exported_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        return (
            "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'><title>{html.escape(title)}</title>"
            f"<style>{cls._resume_styles()}</style></head><body><main class='resume-sheet'>"
            f"<div class='export-meta'>导出时间：{exported_at}</div><article class='resume-content'>{body}</article>"
            "</main></body></html>"
        )

    @staticmethod
    def _html_document(title: str, report: dict[str, Any]) -> str:
        """Render a self-contained escaped generic report document."""
        body = html.escape(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return f"<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><title>{html.escape(title)}</title><style>body{{font-family:Arial,'Microsoft YaHei',sans-serif;max-width:900px;margin:40px auto;color:#172033;line-height:1.65}}h1{{border-bottom:2px solid #0f766e;padding-bottom:12px}}pre{{white-space:pre-wrap;word-break:break-word;background:#f8fafc;padding:20px;border-radius:10px}}</style></head><body><h1>{html.escape(title)}</h1><p>导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}</p><pre>{body}</pre></body></html>"

    @staticmethod
    def _plain_inline_markdown(text: str) -> str:
        """Remove visual Markdown markers while preserving their readable text."""
        text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
        return re.sub(r"[*_`~]", "", text).strip()

    @classmethod
    def _markdown_blocks(cls, markdown: str) -> list[tuple[str, str]]:
        """Parse the generated-resume block subset into PDF layout primitives."""
        blocks: list[tuple[str, str]] = []
        paragraph: list[str] = []

        def flush() -> None:
            if paragraph:
                blocks.append(("paragraph", " ".join(paragraph)))
                paragraph.clear()

        for raw_line in markdown.replace("\r\n", "\n").split("\n"):
            line = raw_line.strip()
            if not line:
                flush()
                continue
            heading = re.match(r"^(#{1,3})\s+(.+)$", line)
            if heading:
                flush()
                blocks.append((f"h{len(heading.group(1))}", cls._plain_inline_markdown(heading.group(2))))
                continue
            bullet = re.match(r"^[-*+]\s+(.+)$", line)
            numbered = re.match(r"^(\d+)[.)]\s+(.+)$", line)
            if bullet:
                flush()
                blocks.append(("bullet", cls._plain_inline_markdown(bullet.group(1))))
                continue
            if numbered:
                flush()
                blocks.append(("number", f"{numbered.group(1)}. {cls._plain_inline_markdown(numbered.group(2))}"))
                continue
            paragraph.append(cls._plain_inline_markdown(line))
        flush()
        return blocks

    @staticmethod
    def _wrap_pdf_text(text: str, width: float, fontname: str, fontsize: float) -> list[str]:
        """Wrap Chinese, Latin text and long URLs by measured glyph width."""
        if not text:
            return [""]
        lines: list[str] = []
        current = ""
        for char in text:
            candidate = current + char
            if current and fitz.get_text_length(candidate, fontname=fontname, fontsize=fontsize) > width:
                lines.append(current.rstrip())
                current = char.lstrip()
            else:
                current = candidate
        if current or not lines:
            lines.append(current.rstrip())
        return lines

    @classmethod
    def _pdf_from_blocks(cls, blocks: list[tuple[str, str]]) -> bytes:
        """Lay out measured lines individually so oversized text can never yield a blank PDF."""
        document = fitz.open()
        page_width, page_height = fitz.paper_size("a4")
        margin_x, top_y, bottom_y = 48.0, 44.0, page_height - 42.0
        content_width = page_width - margin_x * 2
        fontname = "china-s"
        teal = (0.059, 0.463, 0.431)
        teal_dark = (0.086, 0.306, 0.388)
        ink = (0.09, 0.126, 0.2)
        muted = (0.24, 0.318, 0.4)
        white = (1.0, 1.0, 1.0)
        page = None
        y = top_y

        def new_page():
            nonlocal page, y
            page = document.new_page(width=page_width, height=page_height)
            page.draw_rect(fitz.Rect(0, 0, page_width, 18), color=teal_dark, fill=teal_dark, overlay=True)
            page.draw_rect(fitz.Rect(0, 18, page_width, 22), color=teal, fill=teal, overlay=True)
            y = top_y

        def ensure(height: float) -> None:
            if page is None or y + height > bottom_y:
                new_page()

        new_page()
        for kind, text in blocks:
            if not text:
                continue
            if kind == "h1":
                fontsize, leading, before, after, color = 24.0, 29.0, 2.0, 12.0, teal_dark
                lines = cls._wrap_pdf_text(text, content_width, fontname, fontsize)
                ensure(before + len(lines) * leading + after)
                y += before
                for line in lines:
                    line_width = fitz.get_text_length(line, fontname=fontname, fontsize=fontsize)
                    page.insert_text(((page_width - line_width) / 2, y + fontsize), line, fontname=fontname, fontsize=fontsize, color=color)
                    y += leading
                y += after
                continue
            if kind == "h2":
                fontsize, leading = 11.5, 17.0
                lines = cls._wrap_pdf_text(text, content_width - 16, fontname, fontsize)
                height = max(24.0, len(lines) * leading + 8.0)
                ensure(height + 10.0)
                y += 7.0
                page.draw_rect(fitz.Rect(margin_x, y, page_width - margin_x, y + height), color=teal_dark, fill=teal_dark, overlay=True)
                line_y = y + 5.0
                for line in lines:
                    page.insert_text((margin_x + 8, line_y + fontsize), line, fontname=fontname, fontsize=fontsize, color=white)
                    line_y += leading
                y += height + 5.0
                continue
            if kind == "h3":
                fontsize, leading = 11.0, 16.0
                lines = cls._wrap_pdf_text(text, content_width - 12, fontname, fontsize)
                ensure(len(lines) * leading + 9.0)
                y += 4.0
                page.draw_rect(fitz.Rect(margin_x, y, margin_x + 4, y + len(lines) * leading), color=teal, fill=teal, overlay=True)
                for line in lines:
                    page.insert_text((margin_x + 10, y + fontsize), line, fontname=fontname, fontsize=fontsize, color=ink)
                    y += leading
                y += 4.0
                continue

            prefix = "• " if kind == "bullet" else ""
            display = prefix + text
            fontsize, leading = 9.4, 14.0
            indent = 10.0 if kind in {"bullet", "number"} else 0.0
            lines = cls._wrap_pdf_text(display, content_width - indent, fontname, fontsize)
            ensure(len(lines) * leading + 4.0)
            for line_index, line in enumerate(lines):
                x = margin_x + (indent if line_index > 0 and kind in {"bullet", "number"} else 0.0)
                page.insert_text((x, y + fontsize), line, fontname=fontname, fontsize=fontsize, color=muted)
                y += leading
            y += 3.0

        page_count = document.page_count
        for index, pdf_page in enumerate(document):
            footer = f"{index + 1} / {page_count}"
            footer_width = fitz.get_text_length(footer, fontname="helv", fontsize=8)
            pdf_page.insert_text(((page_width - footer_width) / 2, page_height - 18), footer, fontname="helv", fontsize=8, color=(0.58, 0.64, 0.71))
        data = document.tobytes(garbage=4, deflate=True)
        document.close()
        return data

    @classmethod
    def _resume_pdf_bytes(cls, markdown: str) -> bytes:
        """Create a colored, paginated PDF from generated resume Markdown."""
        return cls._pdf_from_blocks(cls._markdown_blocks(markdown))

    @classmethod
    def _pdf_bytes(cls, title: str, report: dict[str, Any]) -> bytes:
        """Create a readable generic PDF without relying on all-or-nothing text boxes."""
        blocks = [("h1", title)]
        blocks.extend(("paragraph", line) for line in json.dumps(report, ensure_ascii=False, indent=2, default=str).splitlines())
        return cls._pdf_from_blocks(blocks)

    async def export(self, request: ArtifactExportRequest, user_id: str) -> ArtifactModel:
        """Regenerate a format-specific private export after owner-scoping its source record."""
        title, report, agent_run_id = await self._source(request, user_id)
        if request.source_type in {"generated_resume", "interview_report"}:
            markdown = str(
                report.get("最终简历")
                if request.source_type == "generated_resume"
                else report.get("markdown")
                or ""
            )
            content = (
                self._resume_html_document(title, markdown).encode("utf-8")
                if request.format == "html"
                else self._resume_pdf_bytes(markdown)
            )
        else:
            content = self._html_document(title, report).encode("utf-8") if request.format == "html" else self._pdf_bytes(title, report)
        digest = hashlib.sha256(content).hexdigest()
        filename = self._safe_filename(title, request.format)
        storage_key = f"{hashlib.sha256(user_id.encode()).hexdigest()[:16]}/{request.source_type}/{request.source_id}/{digest[:16]}-{filename}"
        path = self._path(storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
            temporary.write(content)
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)
        now = self._now()
        async with async_session() as session:
            existing = await session.scalar(select(ArtifactModel).where(ArtifactModel.user_id == user_id, ArtifactModel.source_type == request.source_type, ArtifactModel.source_id == request.source_id, ArtifactModel.format == request.format).with_for_update())
            if existing:
                existing.title, existing.storage_key, existing.size_bytes, existing.checksum_sha256, existing.updated_at = title, storage_key, len(content), digest, now
                await session.commit()
                await session.refresh(existing)
                return existing
            artifact = ArtifactModel(user_id=user_id, source_type=request.source_type, source_id=request.source_id, agent_run_id=agent_run_id, title=title, format=request.format, mime_type=_MIME[request.format], storage_key=storage_key, size_bytes=len(content), checksum_sha256=digest, created_at=now, updated_at=now)
            session.add(artifact)
            await session.commit()
            await session.refresh(artifact)
            return artifact

    def _path(self, storage_key: str) -> Path:
        """Resolve only a storage key inside the configured root to prevent traversal outside the volume."""
        path = (self._root / storage_key).resolve()
        if self._root not in path.parents:
            raise ArtifactNotFound()
        return path

    async def get_download(self, artifact_id: int, user_id: str) -> tuple[ArtifactModel, Path]:
        """Load metadata and file only when both artifact and file belong to the requesting owner."""
        async with async_session() as session:
            artifact = await session.scalar(select(ArtifactModel).where(ArtifactModel.id == artifact_id, ArtifactModel.user_id == user_id))
        if not artifact:
            raise ArtifactNotFound()
        path = self._path(artifact.storage_key)
        if not path.is_file():
            raise ArtifactNotFound()
        return artifact, path
