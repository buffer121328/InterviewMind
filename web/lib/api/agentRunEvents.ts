import { apiRequest, getUserId, API_BASE_URL } from './config';
import { parseSseFrames } from '../sse';
import { parseStreamEvent } from '../streamEvents';
import type { AgentRunEvent } from './agentRunTypes';

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
        const parsed = parseSseFrames(buffer, decoder.decode(value, { stream: true }));
        buffer = parsed.buffer;
        for (const frame of parsed.frames) {
            const event = parseStreamEvent(frame.data);
            if (event?.type === 'agent_run_event') {
                onEvent(event.content);
            }
        }
    }
}
