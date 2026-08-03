import { apiRequest } from './config';

/** Unified session-report payload rendered as Markdown and exported by the backend. */
export interface SessionMarkdownReport {
    success: boolean;
    session_id: string;
    markdown: string;
    generated_at?: string | null;
    message?: string | null;
    company_profile?: Record<string, unknown> | null;
}

/** Reads one owner-scoped report without exposing its underlying profile JSON or resume snapshot. */
export async function getSessionInterviewReport(sessionId: string): Promise<SessionMarkdownReport> {
    try {
        return await apiRequest<SessionMarkdownReport>(`/api/chat/report/session/${sessionId}`);
    } catch (error) {
        return {
            success: false,
            session_id: sessionId,
            markdown: '',
            message: error instanceof Error ? error.message : '读取面试报告失败',
        };
    }
}
