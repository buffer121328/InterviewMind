"""
数据访问层 (Repositories)

按领域分组：
- session/: session_repo + repo_impl (会话、消息、画像与面试计划)
- resume/: resume_repo, resume_generation_repo, candidate_material_repo, jd_analysis_repo, project_rewrite_repo
- interview/: question_bank_repo, retrieval_repo, weakness_report_repo
- application/: job_application_repo, application_event_repo
"""

from app.db.repositories.session.session_repo import SessionRepo, session_repo
