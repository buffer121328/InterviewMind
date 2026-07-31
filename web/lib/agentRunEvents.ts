import type { AgentRun, AgentRunEvent, AgentRunPlanStep, AgentRunStatus, AgentRunEventType } from './api/agentRunTypes';

const TERMINAL_STATUSES = new Set<AgentRunStatus>(['succeeded', 'failed', 'cancelled']);
const SUPPORTED_SCHEMA_VERSION = 1;
const KNOWN_AGENT_RUN_EVENT_TYPES = new Set<AgentRunEventType>([
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
]);

/** Encapsulates string payload; returns typed data or state and keeps side effects within the owning module boundary. */
function stringPayload(payload: Record<string, unknown>, key: string): string | undefined {
    const value = payload[key];
    return typeof value === 'string' && value.length > 0 ? value : undefined;
}

/** Encapsulates number payload; returns typed data or state and keeps side effects within the owning module boundary. */
function numberPayload(payload: Record<string, unknown>, key: string): number | undefined {
    const value = payload[key];
    return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}


/** Determines whether is record so callers can apply the same UI or safety boundary consistently. */
function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Parses agent run event envelope at the frontend boundary and returns a typed safe fallback when the payload is malformed or missing. */
export function parseAgentRunEventEnvelope(content: unknown): AgentRunEvent | null {
    try {
        const value = typeof content === 'string' ? JSON.parse(content) : content;
        if (!isRecord(value)) return null;
        if (typeof value.run_id !== 'string' || typeof value.type !== 'string') return null;
        const eventType = value.type as AgentRunEventType;
        if (!KNOWN_AGENT_RUN_EVENT_TYPES.has(eventType)) return null;
        const schemaVersion = typeof value.schema_version === 'number' ? value.schema_version : SUPPORTED_SCHEMA_VERSION;
        if (schemaVersion !== SUPPORTED_SCHEMA_VERSION) return null;
        return {
            event_id: typeof value.event_id === 'string' ? value.event_id : '',
            run_id: value.run_id,
            sequence: typeof value.sequence === 'number' ? value.sequence : 0,
            type: eventType,
            stage: typeof value.stage === 'string' || value.stage === null ? value.stage : null,
            payload: isRecord(value.payload) ? value.payload : {},
            schema_version: schemaVersion,
            timestamp: typeof value.timestamp === 'string' ? value.timestamp : new Date().toISOString(),
        };
    } catch {
        return null;
    }
}

/** Encapsulates update plan by stage; returns typed data or state and keeps side effects within the owning module boundary. */
function updatePlanByStage(
    plan: AgentRunPlanStep[],
    stage: string | null | undefined,
    terminalStatus?: Extract<AgentRunStatus, 'succeeded' | 'failed' | 'cancelled'>,
): AgentRunPlanStep[] {
    if (plan.length === 0) return plan;
    if (terminalStatus === 'succeeded') {
        return plan.map(step => ({ ...step, status: 'completed' }));
    }

    const stageIndex = stage ? plan.findIndex(step => step.id === stage) : -1;
    if (stageIndex < 0) {
        if (terminalStatus === 'failed' || terminalStatus === 'cancelled') {
            return plan.map(step => (step.status === 'running' ? { ...step, status: 'failed' } : step));
        }
        return plan;
    }

    return plan.map((step, index) => {
        if (terminalStatus === 'failed' || terminalStatus === 'cancelled') {
            if (index < stageIndex) return { ...step, status: 'completed' };
            if (index === stageIndex) return { ...step, status: 'failed' };
            return { ...step, status: 'pending' };
        }
        if (index < stageIndex) return { ...step, status: 'completed' };
        if (index === stageIndex) return { ...step, status: 'running' };
        return { ...step, status: 'pending' };
    });
}

/** Encapsulates with common fields; returns typed data or state and keeps side effects within the owning module boundary. */
function withCommonFields(run: AgentRun, event: AgentRunEvent, updates: Partial<AgentRun>): AgentRun {
    return {
        ...run,
        ...updates,
        updated_at: event.timestamp || run.updated_at,
    };
}

/** Determines whether is terminal agent run event so callers can apply the same UI or safety boundary consistently. */
export function isTerminalAgentRunEvent(event: AgentRunEvent): boolean {
    return event.type === 'run.completed' || event.type === 'run.failed' || event.type === 'run.cancelled';
}

/** Encapsulates apply agent run event; returns typed data or state and keeps side effects within the owning module boundary. */
export function applyAgentRunEvent(run: AgentRun, event: AgentRunEvent): AgentRun {
    if (run.run_id !== event.run_id) return run;

    switch (event.type) {
        case 'run.started': {
            const attempt = numberPayload(event.payload, 'attempt');
            return withCommonFields(run, event, {
                status: 'running',
                stage: event.stage || run.stage,
                attempts: attempt ?? run.attempts,
                can_cancel: true,
                plan: updatePlanByStage(run.plan, event.stage),
                started_at: run.started_at || event.timestamp,
                error_message: null,
            });
        }
        case 'run.stage.changed':
            return withCommonFields(run, event, {
                status: TERMINAL_STATUSES.has(run.status) ? run.status : 'running',
                stage: event.stage || run.stage,
                plan: updatePlanByStage(run.plan, event.stage),
            });
        case 'run.completed':
            return withCommonFields(run, event, {
                status: 'succeeded',
                stage: event.stage || run.stage || 'succeeded',
                plan: updatePlanByStage(run.plan, event.stage, 'succeeded'),
                can_cancel: false,
                can_retry: false,
                error_message: null,
                finished_at: run.finished_at || event.timestamp,
            });
        case 'run.failed':
            return withCommonFields(run, event, {
                status: 'failed',
                stage: event.stage || run.stage,
                plan: updatePlanByStage(run.plan, event.stage, 'failed'),
                can_cancel: false,
                can_retry: run.attempts < run.max_attempts,
                error_message: stringPayload(event.payload, 'message') || run.error_message || '任务执行失败',
                finished_at: run.finished_at || event.timestamp,
            });
        case 'run.cancelled':
            return withCommonFields(run, event, {
                status: 'cancelled',
                stage: event.stage || run.stage || 'cancelled',
                plan: updatePlanByStage(run.plan, event.stage, 'cancelled'),
                can_cancel: false,
                can_retry: false,
                error_message: stringPayload(event.payload, 'message') || run.error_message,
                finished_at: run.finished_at || event.timestamp,
            });
        case 'run.cancel.requested':
            return withCommonFields(run, event, {
                status: 'cancel_requested',
                can_cancel: false,
                error_message: stringPayload(event.payload, 'message') || run.error_message || '正在请求取消当前任务',
            });
        case 'run.retry.requested': {
            const nextAttempt = numberPayload(event.payload, 'next_attempt');
            return withCommonFields(run, event, {
                status: 'retrying',
                stage: event.stage || 'queued',
                attempts: nextAttempt ? Math.max(run.attempts, nextAttempt - 1) : run.attempts,
                can_cancel: true,
                can_retry: false,
                error_message: null,
                plan: updatePlanByStage(run.plan, event.stage || 'queued'),
            });
        }
        case 'run.recovered':
        case 'run.requeued':
            return withCommonFields(run, event, {
                status: 'retrying',
                stage: event.stage || 'queued',
                can_cancel: true,
                can_retry: false,
                plan: updatePlanByStage(run.plan, event.stage || 'queued'),
            });
        case 'run.created':
        default:
            return withCommonFields(run, event, {});
    }
}

/** Renders the apply agent run event list UI and coordinates its typed props, local state, and approved backend interactions. */
export function applyAgentRunEventList(runs: AgentRun[], event: AgentRunEvent): AgentRun[] {
    return runs.map(run => (run.run_id === event.run_id ? applyAgentRunEvent(run, event) : run));
}

export type InteractiveExecutionPlanStepStatus = 'pending' | 'running' | 'completed' | 'failed';

export interface InteractiveExecutionPlanStep {
    id: string;
    title: string;
    status: InteractiveExecutionPlanStepStatus;
}

const INTERACTIVE_PLAN_STEPS: InteractiveExecutionPlanStep[] = [
    { id: 'save_answer', title: '记录本轮回答', status: 'pending' },
    { id: 'analyze_answer', title: '分析回答并决定追问策略', status: 'pending' },
    { id: 'generate_response', title: '生成反馈与下一题', status: 'pending' },
    { id: 'update_progress', title: '更新面试进度', status: 'pending' },
];

/** Builds interactive execution plan from typed frontend state without bypassing backend validation. */
export function buildInteractiveExecutionPlan(events: AgentRunEvent[]): InteractiveExecutionPlanStep[] {
    const latest = events[events.length - 1];
    if (!latest) return INTERACTIVE_PLAN_STEPS.map(step => ({ ...step }));
    const failed = latest.type === 'run.failed' || latest.type === 'run.cancelled';
    const completed = latest.type === 'run.completed';
    const stage = latest.stage || '';

    return INTERACTIVE_PLAN_STEPS.map(step => {
        if (completed) return { ...step, status: 'completed' };
        if (failed) return { ...step, status: step.id === 'generate_response' ? 'failed' : step.status };
        if (stage === 'saving_answer') {
            return step.id === 'save_answer' ? { ...step, status: 'running' } : { ...step };
        }
        if (stage === 'generating_response') {
            if (step.id === 'save_answer' || step.id === 'analyze_answer') return { ...step, status: 'completed' };
            if (step.id === 'generate_response') return { ...step, status: 'running' };
        }
        if (stage === 'saving_response') {
            if (step.id !== 'update_progress') return { ...step, status: 'completed' };
            return { ...step, status: 'running' };
        }
        return { ...step };
    });
}
