import type { AgentRun } from './api/agentRunTypes.ts';
import type {
    InterviewEvaluationDraftAnnotation,
    InterviewEvaluationDraftCase,
    InterviewEvaluationDraftResult,
    InterviewEvaluationSourceSession,
} from './api/evaluations.ts';

export interface InterviewEvaluationReviewCase extends InterviewEvaluationDraftCase {
    included: boolean;
    reviewed: boolean;
    review_error: string | null;
    annotation: InterviewEvaluationDraftAnnotation | null;
}

export type InterviewEvaluationSourceView =
    | { state: 'ready'; message: null }
    | { state: 'not_completed' | 'loading' | 'missing' | 'ineligible'; message: string };

/** Derives the empty/selection state rendered before any model drafting starts. */
export function interviewEvaluationSourceView(input: {
    completed: boolean;
    loading: boolean;
    source: InterviewEvaluationSourceSession | null;
    ineligibilityMessage?: string;
}): InterviewEvaluationSourceView {
    if (!input.completed) return { state: 'not_completed', message: '只有已完成面试可加入评测集。' };
    if (input.loading) return { state: 'loading', message: '正在读取持久化问答记录…' };
    if (!input.source) return { state: 'missing', message: '未找到当前面试的可评测来源。' };
    if (!input.source.eligible) {
        return {
            state: 'ineligible',
            message: input.ineligibilityMessage || '当前面试缺少可复现上下文，暂不能加入评测集。',
        };
    }
    return { state: 'ready', message: null };
}

/** Keeps owner/source-drift/name-conflict messages actionable without exposing stack details. */
export function interviewEvaluationErrorMessage(error: unknown, fallback: string): string {
    return error instanceof Error && error.message.trim() ? error.message : fallback;
}

/** Produces the bounded main-page handoff after a Dataset is confirmed. */
export function buildInterviewEvaluationHandoff(datasetId: string): { view: 'evaluations'; datasetId: string } {
    return { view: 'evaluations', datasetId };
}

/** Narrows an AgentRun result to the server-owned needs-review draft contract. */
export function interviewDraftResult(run: AgentRun | null): InterviewEvaluationDraftResult | null {
    if (!run?.result || run.result.status !== 'needs_review' || !Array.isArray(run.result.cases)) return null;
    return run.result as unknown as InterviewEvaluationDraftResult;
}

/** Initializes mandatory review state without auto-reviewing model output. */
export function initializeInterviewReviewCases(result: InterviewEvaluationDraftResult | null): InterviewEvaluationReviewCase[] {
    return (result?.cases || []).map(item => ({
        ...item,
        included: item.validation_status === 'valid',
        reviewed: false,
        review_error: null,
        annotation: item.annotation ? { ...item.annotation } : null,
    }));
}

/** Confirmation is allowed only when every included case is valid, reviewed, and annotated. */
export function canConfirmInterviewDataset(cases: InterviewEvaluationReviewCase[]): boolean {
    const included = cases.filter(item => item.included);
    return included.length > 0 && included.every(item => (
        item.validation_status === 'valid' && item.reviewed && !item.review_error && Boolean(item.annotation)
    ));
}

/** Parses an editable rubric and accepts only JSON objects as the schema requires. */
export function parseInterviewQualityRubric(value: string): Record<string, unknown> {
    const parsed: unknown = JSON.parse(value);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('Quality Rubric 必须是 JSON 对象');
    }
    return parsed as Record<string, unknown>;
}

/** Builds the bounded confirmation body; authoritative input remains server-owned. */
export function buildInterviewDatasetConfirmation(
    name: string,
    version: string,
    cases: InterviewEvaluationReviewCase[],
): Record<string, unknown> {
    return {
        name: name.trim(),
        version: version.trim(),
        cases: cases.map(item => ({
            attempt_id: item.attempt_id,
            included: item.included,
            reviewed: item.reviewed,
            annotation: item.annotation,
        })),
    };
}
