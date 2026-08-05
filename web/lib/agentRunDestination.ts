import type { AgentRun } from '@/lib/api/agentRuns';

export type AgentRunDestination =
    | { kind: 'interview-session'; sessionId: string }
    | { kind: 'interview-report'; sessionId: string }
    | { kind: 'generated-resume'; resumeId: number }
    | { kind: 'resume-workspace'; generationSessionId?: string }
    | { kind: 'job'; jobId: number }
    | { kind: 'growth-record' };

function positiveInteger(value: unknown): number | null {
    const parsed = typeof value === 'number' ? value : typeof value === 'string' && value.trim() ? Number(value) : NaN;
    return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
}

function nonEmptyString(value: unknown): string | null {
    return typeof value === 'string' && value.trim() ? value.trim() : null;
}

/** Maps one run to a deterministic business destination using typed persisted references only. */
export function getAgentRunDestination(run: AgentRun): AgentRunDestination | null {
    const result = run.result || {};
    const sessionId = nonEmptyString(run.session_id);

    if (run.task_type === 'interview_report') {
        return sessionId ? { kind: 'interview-report', sessionId } : null;
    }
    if (['interview_start', 'interview_turn', 'voice_interview_turn'].includes(run.task_type)) {
        return sessionId ? { kind: 'interview-session', sessionId } : null;
    }
    if (run.task_type === 'resume_generation') {
        const resumeId = positiveInteger(result.generated_resume_id ?? result.resume_id);
        if (resumeId) return { kind: 'generated-resume', resumeId };
        const generationSessionId = nonEmptyString(result.generation_session_id);
        return generationSessionId ? { kind: 'resume-workspace', generationSessionId } : { kind: 'resume-workspace' };
    }
    if (run.task_type === 'resume_optimize' || run.task_type === 'resume_workspace') {
        return { kind: 'resume-workspace' };
    }
    if (run.task_type === 'job_assets' || run.task_type === 'job_recommendation_capture') {
        const jobId = positiveInteger(result.captured_job_id ?? result.job_id);
        return jobId ? { kind: 'job', jobId } : null;
    }
    if (run.task_type === 'ability_profile') return { kind: 'growth-record' };
    return null;
}

/** Returns the stable primary action label for one destination. */
export function getAgentRunDestinationLabel(destination: AgentRunDestination): string {
    if (destination.kind === 'interview-report') return '查看报告';
    if (destination.kind === 'interview-session') return '返回会话';
    if (destination.kind === 'generated-resume') return '查看简历';
    if (destination.kind === 'resume-workspace') return destination.generationSessionId ? '继续补充信息' : '简历工作台';
    if (destination.kind === 'job') return '查看岗位';
    return '查看成长档案';
}
