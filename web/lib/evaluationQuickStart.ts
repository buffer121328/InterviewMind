/** Prompt candidate metadata passed from Prompt management into one-click evaluation. */
export interface EvaluationPromptCandidate {
    name: string;
    version: string;
    compareProduction: boolean;
}

/**
 * Parses the small allowlisted Prompt handoff payload without exposing other localStorage data.
 * Invalid or incomplete data is ignored so the built-in Agent defaults remain authoritative.
 */
export function parseEvaluationPromptCandidate(raw: string | null): EvaluationPromptCandidate | null {
    if (!raw) return null;
    try {
        const value = JSON.parse(raw) as Record<string, unknown>;
        const name = typeof value.name === 'string' ? value.name.trim() : '';
        const rawVersion = value.version;
        const version = typeof rawVersion === 'string' || typeof rawVersion === 'number'
            ? String(rawVersion).trim()
            : '';
        if (!name || !version) return null;
        return {
            name,
            version,
            compareProduction: value.compareProduction === true,
        };
    } catch {
        return null;
    }
}

/** Returns whether a Prompt candidate belongs to the selected built-in Agent. */
export function promptCandidateMatches(
    candidate: EvaluationPromptCandidate | null,
    agentPromptName: string,
): boolean {
    return candidate?.name === agentPromptName;
}
