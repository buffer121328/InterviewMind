import type { ApiConfig, ResumeOptimizeMode } from './resumeTypes.ts';

export interface ResumeOptimizePayloadParams {
    resume_content: string;
    job_description: string;
    session_ids?: string[];
    include_overall_profile?: boolean;
    mode?: ResumeOptimizeMode;
    api_config: ApiConfig;
}

export function buildResumeOptimizePayload(params: ResumeOptimizePayloadParams) {
    return {
        resume_content: params.resume_content,
        job_description: params.job_description,
        session_ids: params.session_ids || [],
        include_overall_profile: params.include_overall_profile || false,
        mode: params.mode || 'balanced',
        api_config: params.api_config,
    };
}
