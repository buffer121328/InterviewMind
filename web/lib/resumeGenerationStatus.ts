import type { GenerationSessionStatus } from './api/resumeTypes.ts';

/** Narrows unknown values to plain records before reading the generation status envelope. */
function asRecord(value: unknown): Record<string, unknown> | null {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
        ? value as Record<string, unknown>
        : null;
}

/**
 * Unwraps the backend's `{ success, data }` response while retaining compatibility
 * with an older direct-status response. Invalid or unsuccessful responses are ignored.
 */
export function unwrapGenerationSessionStatus(value: unknown): GenerationSessionStatus | null {
    const response = asRecord(value);
    if (!response) return null;

    const candidate = asRecord(response.data) || response;
    if (response.success === false || typeof candidate.session_id !== 'string' || typeof candidate.status !== 'string') {
        return null;
    }
    return candidate as unknown as GenerationSessionStatus;
}
