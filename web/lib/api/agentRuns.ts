import { apiRequest } from './config';
import type { AgentRun, AgentRunStatus, AgentRunTaskType } from './agentRunTypes';

/** A server-defined collection of matching runs. Session groups contain every matching child run; the other group is the legacy unassociated-task bucket. */
export interface GroupedAgentRun {
    group_type: 'session' | 'other';
    session_id: string | null;
    session_title: string | null;
    runs: AgentRun[];
}

/** The paginated grouped-run response. `total` counts interview groups, while `other_total` counts individual unassociated runs. */
export interface GroupedAgentRunsResponse {
    groups: GroupedAgentRun[];
    total: number;
    session_total: number;
    other_total: number;
    limit: number;
    offset: number;
}

export type {
    AgentRun,
    AgentRunEvent,
    AgentRunEventType,
    AgentRunPlanStep,
    AgentRunStatus,
    AgentRunTaskType,
} from './agentRunTypes';
export { AGENT_RUN_EVENT_TYPES } from './agentRunTypes';
export { listAgentRunEvents, streamAgentRunEvents } from './agentRunEvents';

/** Calls the backend for list agent runs; the shared API client supplies request identity and error normalization, and this helper returns the typed endpoint result. */
export async function listAgentRuns(params: {
    status?: AgentRunStatus;
    taskType?: AgentRunTaskType;
    sessionId?: string;
    limit?: number;
    offset?: number;
} = {}): Promise<{ runs: AgentRun[]; total: number; limit: number; offset: number }> {
    const query = new URLSearchParams({
        limit: String(params.limit || 20),
        offset: String(params.offset || 0),
    });
    if (params.status) query.set('status', params.status);
    if (params.taskType) query.set('task_type', params.taskType);
    if (params.sessionId) query.set('session_id', params.sessionId);
    const response = await apiRequest<{ success: boolean; runs: AgentRun[]; total: number; limit: number; offset: number }>(
        `/api/agent-runs?${query}`,
    );
    return { runs: response.runs || [], total: response.total || 0, limit: response.limit, offset: response.offset };
}

/**
 * Lists backend-owned AgentRun groups without reconstructing interview parents in the browser.
 *
 * Pagination applies to interview groups, and each returned session group contains all child
 * runs matching the supplied filters. The API client supplies the user identity header.
 */
export async function listGroupedAgentRuns(params: {
    status?: AgentRunStatus;
    taskType?: AgentRunTaskType;
    limit?: number;
    offset?: number;
} = {}): Promise<GroupedAgentRunsResponse> {
    const query = new URLSearchParams({
        limit: String(params.limit || 20),
        offset: String(params.offset || 0),
    });
    if (params.status) query.set('status', params.status);
    if (params.taskType) query.set('task_type', params.taskType);
    const response = await apiRequest<Partial<GroupedAgentRunsResponse>>(`/api/agent-runs/groups?${query}`);
    return {
        groups: response.groups || [],
        total: response.total || 0,
        session_total: response.session_total ?? response.total ?? 0,
        other_total: response.other_total || 0,
        limit: response.limit ?? params.limit ?? 20,
        offset: response.offset ?? params.offset ?? 0,
    };
}

/** Reads exact unfiltered task-history totals for the Run Center summary cards. */
export async function getAgentRunSummary(): Promise<{ active: number; history: number; succeeded: number; failed: number }> {
    return apiRequest('/api/agent-runs/summary');
}

/** Calls the backend for get agent run; the shared API client supplies request identity and error normalization, and this helper returns the typed endpoint result. */
export async function getAgentRun(runId: string): Promise<AgentRun> {
    return apiRequest<AgentRun>(`/api/agent-runs/${runId}`);
}

/** Calls the backend for get agent run trace link; the shared API client supplies request identity and error normalization, and this helper returns the typed endpoint result. */
export async function getAgentRunTraceLink(runId: string): Promise<{
    available: boolean;
    url: string | null;
    message: string | null;
}> {
    return apiRequest(`/api/agent-runs/${runId}/trace-link`);
}

/** Calls the backend for retry agent run; the shared API client supplies request identity and error normalization, and this helper returns the typed endpoint result. */
export async function retryAgentRun(runId: string): Promise<AgentRun> {
    return apiRequest<AgentRun>(`/api/agent-runs/${runId}/retry`, { method: 'POST' });
}

/** Calls the backend for cancel agent run; the shared API client supplies request identity and error normalization, and this helper returns the typed endpoint result. */
export async function cancelAgentRun(runId: string): Promise<AgentRun> {
    return apiRequest<AgentRun>(`/api/agent-runs/${runId}/cancel`, { method: 'POST' });
}

/** Creates a resumable optimization run; omitting a per-attempt key lets the backend reuse its stable payload digest on retry. */
export async function createResumeOptimizeRun(payload: Record<string, unknown>): Promise<AgentRun | { status: 'succeeded'; result: Record<string, unknown> }> {
    return apiRequest('/api/agent-runs/resume-optimize', {
        method: 'POST',
        body: JSON.stringify(payload),
    });
}

/** Creates the single resumable workspace run. The backend owns orchestration; this client only submits user-approved inputs. */
export async function createResumeWorkspaceRun(payload: Record<string, unknown>): Promise<AgentRun | { status: 'succeeded'; result: Record<string, unknown> }> {
    return apiRequest('/api/agent-runs/resume-workspace', {
        method: 'POST',
        body: JSON.stringify(payload),
    });
}

/** Creates an explicit owner-scoped Ability Profile AgentRun; API keys remain inside the encrypted backend task payload. */
export async function createAbilityProfileRun(payload: Record<string, unknown>): Promise<AgentRun | { status: 'succeeded'; result: Record<string, unknown> }> {
    return apiRequest('/api/agent-runs/ability-profile', {
        method: 'POST',
        headers: { 'Idempotency-Key': crypto.randomUUID() },
        body: JSON.stringify(payload),
    });
}

/** Calls the backend for create interview report run; the shared API client supplies request identity and error normalization, and this helper returns the typed endpoint result. */
export async function createInterviewReportRun(payload: Record<string, unknown>): Promise<AgentRun | { status: 'succeeded'; result: Record<string, unknown> }> {
    return apiRequest('/api/agent-runs/interview-report', {
        method: 'POST',
        headers: { 'Idempotency-Key': crypto.randomUUID() },
        body: JSON.stringify(payload),
    });
}

/** Calls the backend for create job assets run; the shared API client supplies request identity and error normalization, and this helper returns the typed endpoint result. */
export async function createJobAssetsRun(payload: Record<string, unknown>): Promise<AgentRun | { status: 'succeeded'; result: Record<string, unknown> }> {
    return apiRequest('/api/agent-runs/job-assets', {
        method: 'POST',
        headers: { 'Idempotency-Key': crypto.randomUUID() },
        body: JSON.stringify(payload),
    });
}

/** Calls the backend for poll agent run; the shared API client supplies request identity and error normalization, and this helper returns the typed endpoint result. */
export async function pollAgentRun(
    runId: string,
    onUpdate?: (run: AgentRun) => void,
    signal?: AbortSignal,
): Promise<AgentRun> {
    while (true) {
        if (signal?.aborted) throw new DOMException('任务轮询已取消', 'AbortError');
        const run = await getAgentRun(runId);
        onUpdate?.(run);
        if (['succeeded', 'failed', 'cancelled'].includes(run.status)) return run;
        await new Promise<void>((resolve, reject) => {
            /** Handles the on abort callback and keeps the related event or cancellation boundary local to this module. */
            const onAbort = () => {
                window.clearTimeout(timer);
                signal?.removeEventListener('abort', onAbort);
                reject(new DOMException('任务轮询已取消', 'AbortError'));
            };
            const timer = window.setTimeout(() => {
                signal?.removeEventListener('abort', onAbort);
                resolve();
            }, 1200);
            signal?.addEventListener('abort', onAbort, { once: true });
        });
    }
}

/** Loads the owner-scoped local performance aggregate; no model text or credentials are returned. */
export async function getAgentPerformanceOverview(params: { days?: number; taskType?: string; agentName?: string } = {}) {
    const query = new URLSearchParams({ days: String(params.days || 7) });
    if (params.taskType) query.set('task_type', params.taskType);
    if (params.agentName) query.set('agent_name', params.agentName);
    return apiRequest<import('./agentRunTypes').AgentPerformanceOverview>(`/api/agent-runs/performance/overview?${query}`);
}

/** Lists safe local model metric events for the current owner. */
export async function listModelMetricEvents(params: { days?: number; degradationsOnly?: boolean; limit?: number } = {}) {
    const query = new URLSearchParams({ days: String(params.days || 7), limit: String(params.limit || 100) });
    const path = params.degradationsOnly ? 'degradations' : 'model-events';
    return apiRequest<{ events: import('./agentRunTypes').ModelMetricEvent[]; total: number }>(`/api/agent-runs/performance/${path}?${query}`);
}
