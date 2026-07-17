export type AgentRunStatus = 'queued' | 'retrying' | 'running' | 'cancel_requested' | 'succeeded' | 'failed' | 'cancelled';
export type AgentRunTaskType = 'interview_start' | 'interview_turn' | 'voice_interview_turn' | 'resume_optimize' | 'interview_report' | 'job_assets';

export const AGENT_RUN_EVENT_TYPES = [
    'run.created',
    'run.started',
    'run.stage.changed',
    'run.completed',
    'run.failed',
    'run.cancelled',
    'run.cancel.requested',
    'run.retry.requested',
    'run.recovered',
    'run.requeued',
] as const;

export type AgentRunEventType = typeof AGENT_RUN_EVENT_TYPES[number];

export interface AgentRunPlanStep {
    id: string;
    title: string;
    status: 'pending' | 'running' | 'completed' | 'failed';
}

export interface AgentRun {
    run_id: string;
    agent_name: string;
    agent_version: string;
    task_type: AgentRunTaskType;
    title: string;
    status: AgentRunStatus;
    stage: string;
    plan: AgentRunPlanStep[];
    result?: Record<string, unknown> | null;
    error_message?: string | null;
    attempts: number;
    max_attempts: number;
    can_retry: boolean;
    can_cancel: boolean;
    created_at: string;
    updated_at: string;
    started_at?: string | null;
    finished_at?: string | null;
}

export interface AgentRunEvent {
    event_id: string;
    run_id: string;
    sequence: number;
    type: AgentRunEventType;
    stage?: string | null;
    payload: Record<string, unknown>;
    schema_version: number;
    timestamp: string;
}
