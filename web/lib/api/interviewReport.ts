import { apiRequest } from './config';
import type { InterviewReportStatus } from '../interviewReportStatus';

/** Owner-scoped deep session-report payload. */
export interface SessionMarkdownReport {
    success: boolean;
    session_id: string;
    status: InterviewReportStatus;
    markdown: string;
    generated_at?: string | null;
    message?: string | null;
    company_profile?: Record<string, unknown> | null;
    profile?: Record<string, unknown> | null;
    weakness_report?: Record<string, unknown> | null;
}

/** Reads one owner-scoped report without exposing its underlying profile JSON or resume snapshot. */
export async function getSessionInterviewReport(
    sessionId: string,
): Promise<SessionMarkdownReport> {
    try {
        return await apiRequest<SessionMarkdownReport>(`/api/chat/report/session/${sessionId}`);
    } catch (error) {
        return {
            success: false,
            session_id: sessionId,
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
