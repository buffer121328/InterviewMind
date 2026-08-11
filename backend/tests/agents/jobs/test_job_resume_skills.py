"""Regression tests for岗位中心's skills-only resume context."""


def test_extracts_professional_skills_section_only():
    from ai.agents.jobs.resume_skills import extract_professional_skills

    result = extract_professional_skills(
        "姓名：候选人\n教育背景\n计算机技术硕士\n专业技能：\nPython、FastAPI、LangGraph\n项目经历\nAgent 项目"
    )
    assert result.matched is True
    assert result.content == "Python、FastAPI、LangGraph"


def test_supports_markdown_and_english_headings():
    from ai.agents.jobs.resume_skills import extract_professional_skills

    result = extract_professional_skills("# Skills\nPython\nFastAPI\n## Experience\nAgent project")
    assert result.matched is True
    assert result.content == "Python\nFastAPI"


def test_fails_open_without_reliable_skills_heading():
    from ai.agents.jobs.resume_skills import extract_professional_skills

    raw = "计算机技术硕士\nAgent 项目经历"
    result = extract_professional_skills(raw)
    assert result.matched is False
    assert result.content == raw
