"""
统一 Prompt 管理中心
=====================
所有 Agent LLM 调用的 prompt 模板集中在此，按业务域拆分：
- interview.py   面试对话 Agent
- resume.py      简历 Agent
- analysis.py    能力分析
- jobs.py        求职工具
- voice.py       语音面试
"""
from app.services.prompts.interview import (
    build_planner_prompt, build_hints_prompt, build_opening_prompt,
    build_evaluating_prompt, build_feedback_prompt, memo_hint,
)
from app.services.prompts.resume import (
    build_match_analyst_prompt, build_content_writer_prompt, build_hr_reviewer_prompt,
    build_moderator_prompt, build_reflect_prompt, build_refine_prompt,
    build_needs_analysis_prompt, build_draft_generation_prompt, build_draft_optimization_prompt,
    build_fact_check_prompt, build_finalize_review_prompt,
    build_resume_analysis_prompt, build_jd_match_system_prompt, build_jd_match_user_prompt,
    build_assembler_system_prompt, build_assembler_user_prompt, build_assembler_assemble_prompt,
    build_project_rewriter_prompt, build_orchestrator_assemble_prompt,
)
from app.services.prompts.analysis import (
    build_candidate_analysis_prompt, build_weakness_analysis_prompt, build_aggregate_profile_prompt,
)
from app.services.prompts.jobs import (
    build_greeting_prompt, build_job_extraction_prompt,
    build_job_card_extraction_prompt, build_job_card_scoring_prompt,
)
from app.services.prompts.voice import (
    build_voice_system_prompt, get_opening_message, build_tts_system_prompt,
)
