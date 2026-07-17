import { apiRequest, getUserId, API_BASE_URL } from './config';
import type { AgentRun, AgentRunStatus, AgentRunTaskType } from './agentRunTypes';

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

export async function listAgentRuns(params: {
    status?: AgentRunStatus;
    taskType?: AgentRunTaskType;
    limit?: number;
    offset?: number;
} = {}): Promise<{ runs: AgentRun[]; total: number; limit: number; offset: number }> {
    const query = new URLSearchParams({
        limit: String(params.limit || 20),
        offset: String(params.offset || 0),
    });
    if (params.status) query.set('status', params.status);
    if (params.taskType) query.set('task_type', params.taskType);
    const response = await apiRequest<{ success: boolean; runs: AgentRun[]; total: number; limit: number; offset: number }>(
        `/api/agent-runs?${query}`,
    );
    return { runs: response.runs || [], total: response.total || 0, limit: response.limit, offset: response.offset };
}

export async function getAgentRun(runId: string): Promise<AgentRun> {
    return apiRequest<AgentRun>(`/api/agent-runs/${runId}`);
}

export async function retryAgentRun(runId: string): Promise<AgentRun> {
    return apiRequest<AgentRun>(`/api/agent-runs/${runId}/retry`, { method: 'POST' });
}

export async function cancelAgentRun(runId: string): Promise<AgentRun> {
    return apiRequest<AgentRun>(`/api/agent-runs/${runId}/cancel`, { method: 'POST' });
}

export async function createResumeOptimizeRun(payload: Record<string, unknown>): Promise<AgentRun | { status: 'succeeded'; result: Record<string, unknown> }> {
    const response = await fetch(`${API_BASE_URL}/api/agent-runs/resume-optimize`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-User-ID': getUserId(),
            'Idempotency-Key': crypto.randomUUID(),
        },
        body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(`创建简历优化任务失败: HTTP ${response.status}`);
    return response.json();
}

export async function createInterviewReportRun(payload: Record<string, unknown>): Promise<AgentRun | { status: 'succeeded'; result: Record<string, unknown> }> {
    return apiRequest('/api/agent-runs/interview-report', {
        method: 'POST',
        headers: { 'Idempotency-Key': crypto.randomUUID() },
        body: JSON.stringify(payload),
    });
}

export async function createJobAssetsRun(payload: Record<string, unknown>): Promise<AgentRun | { status: 'succeeded'; result: Record<string, unknown> }> {
    return apiRequest('/api/agent-runs/job-assets', {
        method: 'POST',
        headers: { 'Idempotency-Key': crypto.randomUUID() },
        body: JSON.stringify(payload),
    });
}

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
