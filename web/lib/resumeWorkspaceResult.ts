import type { ResumeReviewState, ResumeWorkspaceResult } from './api/resumeTypes.ts';

type UnknownRecord = Record<string, unknown>;

function isRecord(value: unknown): value is UnknownRecord {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isResumeReviewState(value: unknown): value is ResumeReviewState {
    if (!isRecord(value) || !['pending', 'completed', 'not_required'].includes(value.status as string)
        || typeof value.version !== 'number' || !Array.isArray(value.items)) {
        return false;
    }

    return value.items.every(item => isRecord(item)
        && typeof item.item_id === 'string'
        && ['pending', 'approved', 'rejected'].includes(item.status as string));
}

/** Reject incomplete or stale terminal payloads before they can bypass the review/generation flow. */
export function isResumeWorkspaceResult(value: unknown): value is ResumeWorkspaceResult {
    if (!isRecord(value) || value.success !== true || !Number.isFinite(value.result_id)
        || !isRecord(value.competition_analysis) || !isRecord(value.jd_matching)
        || !isRecord(value.content_optimization) || !Array.isArray(value.warnings)
        || !isResumeReviewState(value.review)) {
        return false;
    }

    return value.warnings.every(warning => typeof warning === 'string' || isRecord(warning));
}

/** Produces a bounded, user-safe task failure message from an untrusted response. */
export function safeWorkspaceErrorMessage(value: unknown, fallback: string): string {
    if (!isRecord(value) || typeof value.error_message !== 'string') return fallback;
    const message = value.error_message.trim().replace(/\s+/g, ' ');
    return message ? message.slice(0, 300) : fallback;
}
