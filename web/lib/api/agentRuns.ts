import { apiRequest, getUserId, API_BASE_URL } from './config';

export type AgentRunStatus = 'queued' | 'retrying' | 'running' | 'cancel_requested' | 'succeeded' | 'failed' | 'cancelled';
export type AgentRunTaskType = 'interview_start' | 'interview_turn' | 'voice_interview_turn' | 'resume_optimize' | 'interview_report' | 'job_assets';

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

export interface AgentRunEvent {
    event_id: string;
    run_id: string;
    sequence: number;
    type: string;
    stage?: string | null;
    payload: Record<string, unknown>;
    schema_version: number;
    timestamp: string;
}

export async function listAgentRunEvents(
    runId: string,
    afterSequence = 0,
): Promise<AgentRunEvent[]> {
    const response = await apiRequest<{ events: AgentRunEvent[] }>(
        `/api/agent-runs/${runId}/events?after_sequence=${afterSequence}`,
    );
    return response.events || [];
}

export async function streamAgentRunEvents(
    runId: string,
    onEvent: (event: AgentRunEvent) => void,
    signal?: AbortSignal,
    afterSequence = 0,
): Promise<void> {
    const response = await fetch(
        `${API_BASE_URL}/api/agent-runs/${runId}/events/stream?after_sequence=${afterSequence}`,
        { headers: { 'X-User-ID': getUserId() }, signal },
    );
    if (!response.ok || !response.body) throw new Error(`订阅任务事件失败: HTTP ${response.status}`);

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split('\n\n');
        buffer = frames.pop() || '';
        for (const frame of frames) {
            const dataLine = frame.split('\n').find(line => line.startsWith('data:'));
            if (!dataLine) continue;
            onEvent(JSON.parse(dataLine.slice(5).trim()) as AgentRunEvent);
        }
    }
}
