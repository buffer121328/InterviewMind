export type AgentRunStatus = 'queued' | 'retrying' | 'running' | 'cancel_requested' | 'succeeded' | 'failed' | 'cancelled';
/** Includes the retired collection type so historical AgentRuns remain readable. */
export type AgentRunTaskType = 'interview_start' | 'interview_turn' | 'voice_interview_turn' | 'resume_optimize' | 'resume_workspace' | 'resume_generation' | 'interview_report' | 'job_assets' | 'job_recommendation_capture' | 'interview_experience_collect' | 'ability_profile';

export const AGENT_RUN_EVENT_TYPES = [
    'run.created',
    'run.started',
    'run.stage.changed',
    'run.checkpoint.saved',
    'run.completed',
    'run.failed',
    'run.cancelled',
    'run.cancel.requested',
    'run.retry.requested',
    'run.recovered',
    'run.requeued',
    'tool.execution',
    'guardrail.input',
    'guardrail.output',
] as const;

export type AgentRunEventType = typeof AGENT_RUN_EVENT_TYPES[number];

export interface AgentRunPlanStep {
    id: string;
    title: string;
    status: 'pending' | 'running' | 'completed' | 'failed';
}

export interface AgentRun {
    run_id: string;
    /** Optional interview session owner; absent on legacy and non-session AgentRun records. */
    session_id?: string | null;
    /** Optional, ownership-scoped human-readable title for the linked interview session. */
    session_title?: string | null;
    /** Lifecycle of the linked interview session; unlike `status`, this represents the whole interview. */
    session_status?: string | null;
    /** Number of completed main questions / zero-based next-question index persisted by the interview session. */
    session_question_count?: number | null;
    /** Planned number of main questions for the linked interview session. */
    session_max_questions?: number | null;
    agent_name: string;
    agent_version: string;
    task_type: AgentRunTaskType;
    title: string;
    status: AgentRunStatus;
    stage: string;
    plan: AgentRunPlanStep[];
    result?: Record<string, unknown> | null;
    error_message?: string | null;
    trace_id?: string | null;
    /** Earliest real model-request first-token latency captured for this task; absent for historical/non-streaming runs. */
    first_token_duration_ms?: number | null;
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

export interface AgentPerformanceOverview {
    sample_event_count: number;
    total_matching_events: number;
    run_count: number;
    run_success_rate: number | null;
    logical_call_count: number;
    physical_request_count: number;
    call_amplification: number | null;
    p50_model_duration_ms: number | null;
    p95_model_duration_ms: number | null;
    input_tokens: number;
    output_tokens: number;
    cache_read_tokens: number;
    cache_hit_rate: number | null;
    retry_rate: number | null;
    fallback_rate: number | null;
    timeout_rate: number | null;
    authoritative_context_sample_count: number;
    authoritative_truncation_rate: number | null;
    overflow_strategy_counts: Record<string, number>;
    definitions: Record<string, string>;
}

export interface ModelMetricEvent {
    event_id: string;
    run_id: string;
    trace_id: string | null;
    agent_name: string;
    task_type: AgentRunTaskType;
    stage: string | null;
    event_type: string;
    is_degradation: boolean;
    payload: Record<string, unknown>;
    timestamp: string;
}
