/** User-safe company-series aggregate shown after a completed third interview round. */
export interface CompanySeriesProfileSummary {
    sourceRoundCount: number;
    overallAssessment: string;
    strengths: string[];
    weaknesses: string[];
}

/** Reads a persisted company profile without treating an individual round profile as a series aggregate. */
export function summarizeCompanySeriesProfile(value: unknown): CompanySeriesProfileSummary | null {
    if (!value || typeof value !== 'object') return null;
    const record = value as Record<string, unknown>;
    const profile = record.profile;
    if (!profile || typeof profile !== 'object') return null;
    const profileRecord = profile as Record<string, unknown>;
    const asStrings = (candidate: unknown): string[] => Array.isArray(candidate)
        ? candidate.filter((item): item is string => typeof item === 'string' && Boolean(item.trim()))
        : [];
    const sourceRoundCount = Array.isArray(record.source_session_ids)
        ? record.source_session_ids.length
        : 0;
    return {
        sourceRoundCount,
        overallAssessment: typeof profileRecord.overall_assessment === 'string'
            ? profileRecord.overall_assessment
            : '',
        strengths: asStrings(profileRecord.key_strengths),
        weaknesses: asStrings(profileRecord.key_weaknesses),
    };
}
