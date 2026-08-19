/** User-selectable report modes. Backend callers that omit this value remain compatible with `deep`. */
export type InterviewReportMode = 'standard' | 'deep';

/** Stable report availability states returned by the owner-scoped session report endpoint. */
export type InterviewReportStatus = 'not_ready' | 'ready' | 'degraded';

/** New UI sessions recommend the low-cost PDF-only report, without changing backend defaults. */
export const DEFAULT_NEW_INTERVIEW_REPORT_MODE: InterviewReportMode = 'standard';

export interface InterviewReportDisplayPolicy {
    label: string;
    description: string;
    showStructuredSections: boolean;
    showMarkdown: boolean;
    showHtmlDownload: boolean;
    showPdf: boolean;
    showRecommendedQuestions: boolean;
    showDeepGenerationAction: boolean;
}

/** Normalizes server or persisted values while preserving the backend's legacy deep default. */
export function normalizeInterviewReportMode(value: unknown): InterviewReportMode {
    return value === 'standard' ? 'standard' : 'deep';
}

/** Returns the user-visible artifacts allowed for the selected report mode. */
export function getInterviewReportDisplayPolicy(mode: InterviewReportMode): InterviewReportDisplayPolicy {
    if (mode === 'standard') {
        return {
            label: '标准报告',
            description: '快速生成 PDF，适合快速复盘',
            showStructuredSections: false,
            showMarkdown: false,
            showHtmlDownload: false,
            showPdf: true,
            showRecommendedQuestions: false,
            showDeepGenerationAction: true,
        };
    }
    return {
        label: '深度报告',
        description: '多视角结构化复盘，包含完整分析与导出',
        showStructuredSections: true,
        showMarkdown: true,
        showHtmlDownload: true,
        showPdf: true,
        showRecommendedQuestions: true,
        showDeepGenerationAction: false,
    };
}

/** Converts report states into concise copy without exposing task internals. */
export function getInterviewReportStatusLabel(status: InterviewReportStatus | undefined): string {
    switch (status) {
        case 'ready':
            return '已生成';
        case 'degraded':
            return '已生成（降级）';
        default:
            return '尚未生成';
    }
}
