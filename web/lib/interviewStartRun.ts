import type { AgentRunPlanStep, AgentRunStatus } from './api/agentRunTypes';

/** Persisted result returned when an interview-start AgentRun reaches the succeeded state. */
export interface InterviewStartResult {
    first_question?: string;
    session_title?: string;
    [key: string]: unknown;
}

/** Minimal AgentRun response consumed by interview initialization UIs. */
export interface InterviewStartRunState {
    run_id?: string;
    status?: AgentRunStatus;
    stage?: string;
    plan?: AgentRunPlanStep[];
    result?: InterviewStartResult | null;
    error_message?: string | null;
}

interface WaitForInterviewStartRunOptions {
    signal?: AbortSignal;
    intervalMs?: number;
    onProgress?: (run: InterviewStartRunState) => void;
}

/** Waits without losing abort semantics, so leaving the interview page cancels pending polling immediately. */
function waitForPollInterval(intervalMs: number, signal?: AbortSignal): Promise<void> {
    if (signal?.aborted) {
        return Promise.reject(new DOMException('请求已取消', 'AbortError'));
    }

    return new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
            signal?.removeEventListener('abort', handleAbort);
            resolve();
        }, intervalMs);
        const handleAbort = () => {
            clearTimeout(timer);
            signal?.removeEventListener('abort', handleAbort);
            reject(new DOMException('请求已取消', 'AbortError'));
        };
        signal?.addEventListener('abort', handleAbort, { once: true });
    });
}

/**
 * Resolves a synchronous or queued interview-start response through the recoverable AgentRun contract.
 * The caller owns authenticated HTTP requests; this helper only coordinates terminal-state handling and UI progress.
 */
export async function waitForInterviewStartRun(
    initialRun: InterviewStartRunState,
    loadRun: (runId: string) => Promise<InterviewStartRunState>,
    options: WaitForInterviewStartRunOptions = {},
): Promise<InterviewStartResult> {
    let run = initialRun;
    const intervalMs = options.intervalMs ?? 1200;

    while (run.status !== 'succeeded') {
        if (run.status === 'failed' || run.status === 'cancelled') {
            throw new Error(run.error_message || '面试任务未完成');
        }
        if (!run.run_id) {
            throw new Error('启动面试失败：未返回任务 ID');
        }

        await waitForPollInterval(intervalMs, options.signal);
        run = await loadRun(run.run_id);
        options.onProgress?.(run);
    }

    if (!run.result?.first_question) {
        throw new Error('面试初始化未生成首题');
    }
    return run.result;
}
