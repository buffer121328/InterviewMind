import type { AgentRun } from './api/agentRunTypes';
import type { AgentRunEvent } from './api/agentRunTypes';
import type { GroupedAgentRun } from './api/agentRuns';
import { applyAgentRunEventList } from './agentRunEvents.ts';

export interface AgentRunGroup {
    /** Stable key used by the parent disclosure state, never exposed as user-facing copy. */
    key: string;
    /** Session id for interview groups; null identifies the legacy/non-session bucket. */
    sessionId: string | null;
    /** Human-readable session title when the API could safely resolve one. */
    sessionTitle: string | null;
    runs: AgentRun[];
}

/**
 * Filters first, then groups the visible runs so hidden statuses/types cannot create empty parents.
 * Missing session ids intentionally share the separate legacy-safe “other tasks” group.
 */
export function groupAgentRuns(runs: AgentRun[]): AgentRunGroup[] {
    const groups = new Map<string, AgentRunGroup>();
    for (const run of runs) {
        const sessionId = run.session_id?.trim() || null;
        const sessionTitle = run.session_title?.trim() || null;
        const key = sessionId ? `session:${sessionId}` : 'other';
        const existing = groups.get(key);
        if (existing) {
            existing.runs.push(run);
            existing.sessionTitle ||= sessionTitle;
        } else groups.set(key, { key, sessionId, sessionTitle, runs: [run] });
    }

    for (const group of groups.values()) {
        group.runs.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
    }
    return [...groups.values()].sort((a, b) => {
        if (a.sessionId === null) return 1;
        if (b.sessionId === null) return -1;
        return (b.runs[0]?.updated_at || '').localeCompare(a.runs[0]?.updated_at || '');
    });
}

/**
 * Applies an SSE update to its existing backend-owned group without flattening or regrouping runs.
 * Events for runs outside the current filtered response leave the displayed groups unchanged.
 */
export function applyAgentRunEventGroups(groups: GroupedAgentRun[], event: AgentRunEvent): GroupedAgentRun[] {
    return groups.map(group => ({ ...group, runs: applyAgentRunEventList(group.runs, event) }));
}
