import { buildInteractiveExecutionPlan, parseAgentRunEventEnvelope } from './agentRunEvents.ts';
import type { AgentRunEvent } from './api/agentRunTypes.ts';

type UnknownRecord = Record<string, unknown>;

function isRecord(value: unknown): value is UnknownRecord {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function parseMaybeJson(value: unknown): unknown {
    if (typeof value !== 'string') return value;
    const trimmed = value.trim();
    if (!trimmed) return '';
    try {
        return JSON.parse(trimmed);
    } catch {
        return value;
    }
}

function parseString(value: unknown): string | null {
    return typeof value === 'string' ? value : null;
}

function parseNumber(value: unknown): number | null {
    return typeof value === 'number' && Number.isFinite(value) ? value : null;
}


export type StreamExecutionPlanStepStatus = 'pending' | 'running' | 'completed' | 'failed';

export interface StreamExecutionPlanStep {
    id: string;
    title: string;
    status: StreamExecutionPlanStepStatus;
}

const EXECUTION_PLAN_STATUSES = new Set<StreamExecutionPlanStepStatus>(['pending', 'running', 'completed', 'failed']);

function isExecutionPlanStatus(value: unknown): value is StreamExecutionPlanStepStatus {
    return typeof value === 'string' && EXECUTION_PLAN_STATUSES.has(value as StreamExecutionPlanStepStatus);
}

function isExecutionPlanStep(value: unknown): value is StreamExecutionPlanStep {
    return isRecord(value)
        && typeof value.id === 'string'
        && typeof value.title === 'string'
        && isExecutionPlanStatus(value.status);
}

function parseExecutionPlanSteps(value: unknown): StreamExecutionPlanStep[] {
    return Array.isArray(value) ? value.filter(isExecutionPlanStep) : [];
}

export interface ExecutionPlanReduction {
    executionPlan: StreamExecutionPlanStep[];
    currentInteractiveRunId?: string | null;
}

export interface StreamPlanEvent {
    type: 'plan';
    content: UnknownRecord | UnknownRecord[] | string;
}

export interface StreamStepUpdateEvent {
    type: 'step_update';
    content: { id: string; status: string; [key: string]: unknown };
}

export interface StreamAgentRunEvent {
    type: 'agent_run_event';
    content: AgentRunEvent;
}

export interface StreamTextEvent {
    type: 'text' | 'token' | 'content' | 'audio';
    content: string;
}

export interface StreamProgressEvent {
    type: 'progress';
    current: number;
    total?: number;
}

export interface StreamCompleteEvent {
    type: 'complete';
}

export interface StreamDoneEvent {
    type: 'done';
    content: string;
    result_id?: number;
}

export interface StreamErrorEvent {
    type: 'error';
    content: string;
}

export interface StreamStateUpdateEvent {
    type: 'state_update';
    content: UnknownRecord;
}

export interface StreamWarningEvent {
    type: 'warning';
    node: string;
    message: string;
}

export interface StreamRunEvent {
    type: 'run';
    run_id: string;
}

export interface StreamAuditEvent {
    type: 'audit';
    action: string;
    actor?: string;
    content: UnknownRecord;
}

export type StreamEventCategory = 'run_event' | 'domain_event' | 'ui_delta' | 'audit_event';

export type AppStreamEvent =
    | StreamPlanEvent
    | StreamStepUpdateEvent
    | StreamAgentRunEvent
    | StreamTextEvent
    | StreamProgressEvent
    | StreamCompleteEvent
    | StreamDoneEvent
    | StreamErrorEvent
    | StreamStateUpdateEvent
    | StreamWarningEvent
    | StreamRunEvent
    | StreamAuditEvent;

export function parseStreamEvent(content: unknown): AppStreamEvent | null {
    const value = typeof content === 'string' ? parseMaybeJson(content) : content;
    if (!isRecord(value) || typeof value.type !== 'string') return null;

    switch (value.type) {
        case 'plan': {
            const payload = parseMaybeJson(value.content ?? value.steps ?? value.plan);
            if (Array.isArray(payload) || isRecord(payload) || typeof payload === 'string') {
                return { type: 'plan', content: payload };
            }
            return null;
        }
        case 'step_update': {
            const payload = parseMaybeJson(value.content ?? value.update ?? value.step);
            if (isRecord(payload) && typeof payload.id === 'string' && typeof payload.status === 'string') {
                return { type: 'step_update', content: payload as StreamStepUpdateEvent['content'] };
            }
            return null;
        }
        case 'agent_run_event': {
            const envelope = parseAgentRunEventEnvelope(value.content);
            if (!envelope) return null;
            return { type: 'agent_run_event', content: envelope };
        }
        case 'text':
        case 'token':
        case 'content':
        case 'audio': {
            const payload = parseString(value.content);
            return payload === null ? null : { type: value.type, content: payload };
        }
        case 'progress': {
            const current = parseNumber(value.current);
            if (current === null) return null;
            const total = parseNumber(value.total);
            return total === null ? { type: 'progress', current } : { type: 'progress', current, total };
        }
        case 'complete':
            return { type: 'complete' };
        case 'done': {
            const payload = parseString(value.content ?? value.text ?? value.message) ?? '';
            const resultId = parseNumber(value.result_id);
            return resultId === null ? { type: 'done', content: payload } : { type: 'done', content: payload, result_id: resultId };
        }
        case 'error': {
            const payload = parseString(value.content ?? value.message);
            return payload === null ? null : { type: 'error', content: payload };
        }
        case 'state_update': {
            const payload = parseMaybeJson(value.content ?? value.state);
            return isRecord(payload) ? { type: 'state_update', content: payload } : null;
        }
        case 'warning': {
            const node = parseString(value.node);
            const message = parseString(value.message ?? value.content);
            if (!node || !message) return null;
            return { type: 'warning', node, message };
        }
        case 'run': {
            const runId = parseString(value.run_id);
            return runId ? { type: 'run', run_id: runId } : null;
        }
        case 'audit': {
            const action = parseString(value.action);
            const actor = parseString(value.actor);
            const payload = parseMaybeJson(value.content ?? value.payload ?? {});
            if (!action || !isRecord(payload)) return null;
            return actor ? { type: 'audit', action, actor, content: payload } : { type: 'audit', action, content: payload };
        }
        default:
            return null;
    }
}


export function getStreamEventCategory(event: AppStreamEvent): StreamEventCategory {
    if (event.type === 'agent_run_event' || event.type === 'run') return 'run_event';
    if (event.type === 'audit') return 'audit_event';
    if (event.type === 'plan' || event.type === 'step_update' || event.type === 'state_update' || event.type === 'warning') return 'ui_delta';
    return 'domain_event';
}


export function reduceExecutionPlanStreamEvent(
    currentPlan: StreamExecutionPlanStep[],
    event: AppStreamEvent,
): ExecutionPlanReduction | null {
    if (event.type === 'plan') {
        const planPayload = event.content;
        if (Array.isArray(planPayload)) {
            return { executionPlan: parseExecutionPlanSteps(planPayload) };
        }
        if (isRecord(planPayload)) {
            return {
                executionPlan: parseExecutionPlanSteps(planPayload.steps),
                currentInteractiveRunId: typeof planPayload.run_id === 'string' ? planPayload.run_id : null,
            };
        }
        return null;
    }

    if (event.type === 'step_update') {
        const update = event.content;
        if (!isExecutionPlanStatus(update.status)) return null;
        const status = update.status;
        return {
            executionPlan: currentPlan.map(step => (
                step.id === update.id ? { ...step, status } : step
            )),
        };
    }

    if (event.type === 'agent_run_event') {
        return {
            currentInteractiveRunId: event.content.run_id,
            executionPlan: buildInteractiveExecutionPlan([event.content]),
        };
    }

    return null;
}
