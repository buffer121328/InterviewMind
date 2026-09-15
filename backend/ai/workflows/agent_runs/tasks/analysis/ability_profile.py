"""提供能力画像相关后端功能。"""

from ai.workflows.agent_runs.contracts import ProgressCallback
from observability import agent_observation


async def execute_ability_profile(payload: dict, user_id: str, progress: ProgressCallback) -> dict:
    """执行能力画像相关后端逻辑。"""
    from ai.workflows.analysis.ability_service import get_ability_service
    from app.domain.ability_growth import ability_profile_not_ready_message

    run_id = str(payload.get("_agent_run_id") or "") or None
    api_config = payload.get("api_config")
    async with agent_observation(
        name="ability-profile",
        agent_type="ability_profile",
        user_id=user_id,
        session_id=None,
        run_id=run_id,
        input_payload={"explicit_generation": True},
    ) as observation:
        await progress("loading_profiles")
        service = get_ability_service()
        profiles = await service.session_repo.get_series_final_profiles(limit=5, user_id=user_id)
        profile_progress = await service.get_profile_progress(user_id)
        await progress("selecting_reviewers")
        if not profiles:
            result = {
                "success": False,
                "message": ability_profile_not_ready_message(profile_progress),
                "sample_count": 0,
                "progress": profile_progress,
            }
            observation.set_output({"sample_count": 0, "reviewer_count": 0})
            return result
        await progress("aggregating_profile")
        generated = await service.generate_overall_profile(user_id=user_id, api_config=api_config)
        await progress("saving_profile")
        profile = generated["profile"]
        result = {
            "success": True,
            "profile": profile.model_dump() if hasattr(profile, "model_dump") else profile,
            "sample_count": len(profiles),
            "warning": generated.get("warning"),
            "destination": {"kind": "growth-record"},
        }
        observation.set_output({"sample_count": len(profiles), "has_warning": bool(generated.get("warning"))})
        return result
