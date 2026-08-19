import { apiRequest } from './config';
import { normalizeInterviewReportMode, type InterviewReportMode, type InterviewReportStatus } from '../interviewReportMode';

/** Owner-scoped PDF metadata exposed for standard reports without a storage path. */
export interface ReportPdfArtifact {
    id: number;
    title: string;
    format: 'pdf' | string;
    mime_type: string;
    size_bytes: number;
    created_at: string;
    download_url: string;
    artifact_mode: InterviewReportMode;
    report_source_version: string;
}

/** Unified session-report payload. Standard reports intentionally omit deep source-derived sections. */
export interface SessionMarkdownReport {
    success: boolean;
    session_id: string;
    report_mode: InterviewReportMode;
    status: InterviewReportStatus;
    report_quality?: 'model_reviewed' | 'degraded_evidence_only' | 'unknown_legacy' | string | null;
    degradation_reason?: 'model_timeout' | 'output_contract_failure' | 'model_unavailable' | string | null;
    markdown: string;
    generated_at?: string | null;
    message?: string | null;
    company_profile?: Record<string, unknown> | null;
    profile?: Record<string, unknown> | null;
    weakness_report?: Record<string, unknown> | null;
    pdf_artifact?: ReportPdfArtifact | null;
}

/** Reads one owner-scoped report without exposing its underlying profile JSON or resume snapshot. */
export async function getSessionInterviewReport(
    sessionId: string,
    reportMode: InterviewReportMode = 'deep',
): Promise<SessionMarkdownReport> {
    const normalizedMode = normalizeInterviewReportMode(reportMode);
    try {
        return await apiRequest<SessionMarkdownReport>(
            `/api/chat/report/session/${sessionId}?${new URLSearchParams({ report_mode: normalizedMode })}`,
        );
    } catch (error) {
        return {
            success: false,
            session_id: sessionId,
            report_mode: normalizedMode,
            status: 'not_ready',
            markdown: '',
            message: error instanceof Error ? error.message : '读取面试报告失败',
        };
    }
}

/** Saves selected persisted recommendation indices without trusting client-provided question text. */
export async function saveSessionReportQuestions(sessionId: string, questionIndices: number[]): Promise<{ success: boolean; saved_count: number; skipped_count: number; item_ids: number[] }> {
    return apiRequest(`/api/chat/report/session/${sessionId}/questions`, {
        method: 'POST',
        body: JSON.stringify({ question_indices: questionIndices }),
    });
}
