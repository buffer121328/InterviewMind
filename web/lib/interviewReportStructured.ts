import type { SessionMarkdownReport } from './api/interviewReport.ts';

type UnknownRecord = Record<string, unknown>;
const record = (value: unknown): UnknownRecord => typeof value === 'object' && value !== null && !Array.isArray(value) ? value as UnknownRecord : {};
const strings = (value: unknown): string[] => Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string' && Boolean(item.trim())) : [];
const records = (value: unknown): UnknownRecord[] => Array.isArray(value) ? value.map(record).filter(item => Object.keys(item).length > 0) : [];

/** Normalizes current and historical report payloads into stable UI collections. */
export function normalizeStructuredInterviewReport(report: Partial<SessionMarkdownReport> | null) {
    const profile = record(report?.profile);
    const weakness = record(report?.weakness_report);
    return {
        profile: {
            overall_assessment: typeof profile.overall_assessment === 'string' ? profile.overall_assessment : '',
            recommendation: typeof profile.recommendation === 'string' ? profile.recommendation : '',
            dimensions: Object.fromEntries(Object.entries(record(profile.dimensions)).map(([key, value]) => [key, record(value)])) as Record<string, UnknownRecord>,
            key_strengths: strings(profile.key_strengths),
            key_weaknesses: strings(profile.key_weaknesses),
        },
        weaknessReport: {
            weaknessCategories: records(weakness.weakness_categories),
            questionFailures: records(weakness.question_failures),
            questionEvidence: records(weakness.question_evidence),
            improvementActions: records(weakness.improvement_actions),
            recommendedQuestions: strings(weakness.recommended_questions),
            priorityOrder: strings(weakness.priority_order),
        },
    };
}
