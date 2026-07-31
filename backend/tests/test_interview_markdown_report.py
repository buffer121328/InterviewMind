"""Regression tests for the unified interview Markdown report."""

from app.domain.interview_reports import build_interview_report_markdown
from app.files.artifact_service import ArtifactService


def _dimension(score: int) -> dict[str, object]:
    """Return one complete ability-dimension fixture."""
    return {
        "score": score,
        "evidence": "候选人说明了真实项目证据",
        "reason": "取舍清晰",
        "better_answer_example": "补充量化结果",
        "improvement_tip": "使用 STAR 结构",
    }


def test_unified_interview_markdown_contains_profile_weaknesses_and_actions():
    """One Markdown document must include both former report views."""
    profile = {
        key: _dimension(8)
        for key in (
            "professional_competence",
            "execution_results",
            "logic_problem_solving",
            "communication",
            "growth_potential",
            "collaboration",
        )
    }
    profile.update({
        "overall_assessment": "整体表现稳定",
        "recommendation": "hire",
        "key_strengths": ["技术取舍清晰"],
        "key_weaknesses": ["结果量化不足"],
    })
    weakness = {
        "weakness_categories": [
            {"category": "项目表达", "description": "结果证据不足", "severity": "medium"},
        ],
        "question_failures": [
            {
                "question": "介绍一次项目优化",
                "user_answer": "做过优化",
                "issue": "缺少指标",
                "better_example": "说明前后延迟变化",
            },
        ],
        "improvement_actions": [
            {"action": "整理三个 STAR 案例", "priority": 1, "estimated_effort": "1周"},
        ],
        "recommended_questions": ["如何证明优化有效？"],
        "priority_order": ["项目表达"],
    }

    markdown = build_interview_report_markdown(
        title="后端工程师模拟面试",
        mode="mock",
        round_index=1,
        max_questions=10,
        profile=profile,
        weakness_report=weakness,
        generated_at="2026-07-28T10:00:00",
    )

    assert "# 后端工程师模拟面试 · 面试报告" in markdown
    assert "## 能力画像" in markdown
    assert "## 重点短板" in markdown
    assert "## 改进行动" in markdown
    assert "整理三个 STAR 案例" in markdown


def test_unified_interview_markdown_reuses_html_and_pdf_renderers():
    """The shared artifact logic must render the same Markdown to HTML and PDF."""
    markdown = "# 面试报告\n\n## 综合评价\n\n整体表现稳定。\n"

    html = ArtifactService._resume_html_document("面试报告", markdown)
    pdf = ArtifactService._resume_pdf_bytes(markdown)

    assert "<h1>面试报告</h1>" in html
    assert "<h2>综合评价</h2>" in html
    assert pdf.startswith(b"%PDF")
