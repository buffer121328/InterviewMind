"""Regression tests for private report export metadata and download authorization."""

from pathlib import Path

import fitz
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.artifacts import router
from app.files.artifact_service import ArtifactNotFound, ArtifactService


def test_private_report_renderers_generate_html_and_pdf_without_executing_report_html():
    """Report strings are escaped in HTML and both export formats produce their expected bytes."""
    report = {"summary": "<script>alert('unsafe')</script>", "score": 82}

    html_document = ArtifactService._html_document("报告", report)
    pdf = ArtifactService._pdf_bytes("报告", report)

    assert "&lt;script&gt;" in html_document
    assert "<script>" not in html_document
    assert pdf.startswith(b"%PDF")


def test_generated_resume_exports_preserve_markdown_layout_and_render_visible_pdf_text():
    """Generated resumes use the dedicated colored renderer instead of a JSON dump or blank textbox PDF."""
    markdown = """# 郭成

男 | AI应用开发 | gc@example.com

## 项目经历

### InterviewMind | 独立开发

- 设计可恢复 AgentRun 与 SSE 事件重放。
- 使用 **LangGraph** 编排多阶段任务。

## 专业技能

- Python、FastAPI、PostgreSQL
"""

    html_document = ArtifactService._resume_html_document("郭成-AI应用开发", markdown)
    pdf_bytes = ArtifactService._resume_pdf_bytes(markdown)

    assert "resume-sheet" in html_document
    assert "linear-gradient" in html_document
    assert "<h2>项目经历</h2>" in html_document
    assert "最终简历" not in html_document
    assert "&lt;h2&gt;" not in html_document

    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    assert document.page_count >= 1
    extracted = "".join(page.get_text() for page in document)
    assert "郭成" in extracted
    assert "项目经历" in extracted
    pixmap = document[0].get_pixmap(matrix=fitz.Matrix(0.25, 0.25), alpha=False)
    assert len(set(pixmap.samples)) > 8
    document.close()


@pytest.mark.asyncio
async def test_download_rejects_another_users_artifact(monkeypatch, tmp_path: Path):
    """Artifact lookup always combines artifact ID with the current owner before opening volume files."""
    service = ArtifactService(str(tmp_path))

    class FakeSession:
        """Return no artifact for the foreign owner-scoped query."""

        async def scalar(self, _statement):
            """Simulate an owner-scoped database miss."""
            return None

    class FakeSessionContext:
        """Provide the asynchronous session context expected by the service."""

        async def __aenter__(self):
            """Return the query fake."""
            return FakeSession()

        async def __aexit__(self, *_args):
            """Close the no-op fake session."""
            return False

    monkeypatch.setattr("app.files.artifact_service.async_session", lambda: FakeSessionContext())

    with pytest.raises(ArtifactNotFound):
        await service.get_download(1, "different-owner")


def test_download_route_returns_404_for_another_owner(monkeypatch, tmp_path: Path):
    """HTTP download failures are indistinguishable for missing and foreign private files."""
    class FakeService:
        """Reject every download without exposing metadata or storage location."""

        async def get_download(self, _artifact_id, _user_id):
            """Represent an owner-scoped artifact miss."""
            raise ArtifactNotFound()

    monkeypatch.setattr("app.api.artifacts._service", FakeService())
    app = FastAPI()
    app.include_router(router)

    response = TestClient(app).get("/api/artifacts/123/download")

    assert response.status_code == 404
    assert response.json()["detail"] == "文件不存在或无权访问"


def test_default_artifact_storage_is_project_writable_directory(monkeypatch):
    """Local runs must not default to the container-only read-only /app path."""
    from app.config import get_settings

    monkeypatch.delenv("ARTIFACT_STORAGE_DIR", raising=False)
    get_settings.cache_clear()
    try:
        service = ArtifactService()
        backend_root = Path(__file__).resolve().parents[2]
        assert service._root == (backend_root / "data" / "artifacts").resolve()
        assert not str(service._root).startswith("/app/")
    finally:
        get_settings.cache_clear()


def test_export_route_sanitizes_storage_failures(monkeypatch):
    """Filesystem failures return a stable service-unavailable response without leaking paths."""
    from app.files.artifact_service import ArtifactStorageUnavailable

    class FakeService:
        async def export(self, _request, _user_id):
            raise ArtifactStorageUnavailable()

    monkeypatch.setattr("app.api.artifacts._service", FakeService())
    app = FastAPI()
    app.include_router(router)

    response = TestClient(app).post(
        "/api/artifacts/export",
        json={"source_type": "agent_run", "source_id": "run-1", "format": "html"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "导出存储暂不可用，请稍后重试"
    assert "/app/" not in response.text


def test_interview_report_pdf_embeds_cjk_font_and_renders_multpage_body_with_poppler(tmp_path: Path):
    """The report PDF is self-contained: text extracts and an independent renderer sees Chinese body text."""
    import shutil
    import subprocess

    markdown = """# 中文面试报告

## 结论

- 候选人能够说明缓存容量、淘汰策略和一致性边界。

## 改进建议

""" + ("请继续补充量化指标、故障恢复和压测结果，形成可验证的完整回答。" * 180)

    pdf_bytes = ArtifactService._resume_pdf_bytes(markdown)
    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        extracted = "".join(page.get_text() for page in document)
        assert document.page_count >= 2
        assert "中文面试报告" in extracted
        assert any("reportcjk" in str(font).lower() for page in document for font in page.get_fonts(full=True))
    finally:
        document.close()

    pdf_path = tmp_path / "interview-report.pdf"
    pdf_path.write_bytes(pdf_bytes)
    pdftotext = shutil.which("pdftotext")
    pdftoppm = shutil.which("pdftoppm")
    if pdftotext is None or pdftoppm is None:
        pytest.skip("independent PDF rendering requires Poppler; the backend image provides it")
    text_path = tmp_path / "interview-report.txt"
    subprocess.run([pdftotext, "-enc", "UTF-8", str(pdf_path), str(text_path)], check=True)  # noqa: S603
    assert "中文面试报告" in text_path.read_text(encoding="utf-8")
    image_prefix = tmp_path / "interview-report-page"
    subprocess.run([pdftoppm, "-f", "1", "-l", "1", "-png", str(pdf_path), str(image_prefix)], check=True)  # noqa: S603
    rendered = tmp_path / "interview-report-page-1.png"
    assert rendered.is_file()
    assert rendered.stat().st_size > 10_000
