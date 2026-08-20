import type { EvaluationCaseRunDetail, EvaluationScore } from './api/evaluations';

export type EvaluationDisplayOutcome = 'passed' | 'failed' | 'review';

export const EVALUATION_SCORE_RULE_PAGE_SIZE = 10;

export interface EvaluationScorePage {
    scores: EvaluationScore[];
    page: number;
    totalPages: number;
}

/** Returns a bounded ten-rule page without changing the score order from the evaluation service. */
export function paginateEvaluationScores(
    scores: EvaluationScore[],
    requestedPage: number,
    pageSize = EVALUATION_SCORE_RULE_PAGE_SIZE,
): EvaluationScorePage {
    const safePageSize = Math.max(1, Math.floor(pageSize));
    const totalPages = Math.ceil(scores.length / safePageSize);
    const page = totalPages === 0 ? 1 : Math.min(Math.max(1, Math.floor(requestedPage)), totalPages);
    const start = (page - 1) * safePageSize;

    return {
        scores: scores.slice(start, start + safePageSize),
        page,
        totalPages,
    };
}

export interface EvaluationScoreSummary {
    source: string;
    label: string;
    scores: EvaluationScore[];
    passed: number;
    failed: number;
    review: number;
    hardGateFailures: number;
}

export interface EvaluationCaseOutcomeSummary {
    statusLabel: string;
    statusTone: EvaluationDisplayOutcome;
    hardGateLabel: string;
    hardGateTone: EvaluationDisplayOutcome;
    reviewLabel: string;
    reviewTone: EvaluationDisplayOutcome;
    reviewReasons: string[];
    metrics: Array<{ label: string; value: string }>;
}

const SOURCE_LABELS: Record<string, string> = {
    deterministic: '确定性规则',
    deepeval: 'DeepEval',
    judge: 'LLM Judge',
    human: '人工标注',
    user_feedback: '用户反馈',
};

const REVIEW_REASON_LABELS: Record<string, string> = {
    runtime_failure: '运行失败',
    trace_incomplete: 'Trace 不完整',
    hard_gate_failure: '硬门禁失败',
    semantic_not_evaluated: '语义未评测',
    semantic_failure: '语义评测失败',
    tool_selection_execution_conflict: '工具选择/执行冲突',
    dependency_failure_with_success: '依赖失败但业务声称成功',
    external_approval_evidence_missing: '外部审批证据缺失',
    sampled_review: '命中人工抽样',
    judge_disagreement: 'Judge 分歧',
};

const SCORE_PASSED = new Set(['passed', 'pass', 'succeeded', 'success']);
const SCORE_FAILED = new Set(['failed', 'fail', 'blocked', 'error']);

/** Maps an evaluator source to a stable product-facing label. */
export function evaluationScoreSourceLabel(source: string): string {
    return SOURCE_LABELS[source] ?? source;
}

/** Maps a governed review code without exposing the backend enum as the primary UI. */
export function evaluationReviewReasonLabel(reason: string): string {
    return REVIEW_REASON_LABELS[reason] ?? reason;
}

/** Normalizes heterogeneous score status values to the three states used by the UI. */
export function evaluationScoreOutcome(status: string): EvaluationDisplayOutcome {
    const normalized = status.trim().toLowerCase();
    if (SCORE_PASSED.has(normalized)) return 'passed';
    if (SCORE_FAILED.has(normalized)) return 'failed';
    return 'review';
}

/** Groups scores by source and calculates a compact, source-local verdict. */
export function summarizeEvaluationScores(scores: EvaluationScore[]): EvaluationScoreSummary[] {
    const grouped = new Map<string, EvaluationScore[]>();
    for (const score of scores) {
        const group = grouped.get(score.source) ?? [];
        group.push(score);
        grouped.set(score.source, group);
    }
    return [...grouped.entries()].map(([source, group]) => {
        const outcomes = group.map((score) => evaluationScoreOutcome(score.status));
        return {
            source,
            label: evaluationScoreSourceLabel(source),
            scores: group,
            passed: outcomes.filter((outcome) => outcome === 'passed').length,
            failed: outcomes.filter((outcome) => outcome === 'failed').length,
            review: outcomes.filter((outcome) => outcome === 'review').length,
            hardGateFailures: group.filter(
                (score) => score.hard_gate && evaluationScoreOutcome(score.status) === 'failed',
            ).length,
        };
    });
}

/** Produces a non-content summary so output stays compact until the user asks for details. */
export function summarizeEvaluationOutput(output: unknown): string {
    if (output == null) return '未返回实际输出';
    if (typeof output === 'string') return `文本输出 · ${output.length.toLocaleString('zh-CN')} 字符`;
    if (Array.isArray(output)) return `列表输出 · ${output.length.toLocaleString('zh-CN')} 项`;
    if (typeof output === 'object') {
        const record = output as Record<string, unknown>;
        const questions = Array.isArray(record.questions) ? `，含 ${record.questions.length} 个问题` : '';
        return `结构化输出 · ${Object.keys(record).length.toLocaleString('zh-CN')} 个字段${questions}`;
    }
    return `输出类型：${typeof output}`;
}

/** Builds the top-level case verdict without assuming a single adapter payload shape. */
export function summarizeEvaluationCaseOutcome(detail: EvaluationCaseRunDetail): EvaluationCaseOutcomeSummary {
    const runtimeSucceeded = detail.status === 'succeeded' || detail.record.outcome?.runtime_success === true;
    const statusTone: EvaluationDisplayOutcome = runtimeSucceeded ? 'passed' : detail.status === 'failed' ? 'failed' : 'review';
    const estimatedCost = Number(detail.record.estimated_cost_usd);
    const totalTokens = totalTokenUsage(detail.token_usage);
    const metrics = [
        { label: '延迟', value: `${Math.round(detail.latency_ms).toLocaleString('zh-CN')} ms` },
        ...(totalTokens == null ? [] : [{ label: 'Token', value: totalTokens.toLocaleString('zh-CN') }]),
        ...(Number.isFinite(estimatedCost) ? [{ label: '成本', value: formatUsd(estimatedCost) }] : []),
    ];

    return {
        statusLabel: runtimeSucceeded ? '运行成功' : detail.status === 'failed' ? '运行失败' : `运行状态：${detail.status}`,
        statusTone,
        hardGateLabel: detail.hard_gate_passed ? '硬门禁通过' : '硬门禁未通过',
        hardGateTone: detail.hard_gate_passed ? 'passed' : 'failed',
        reviewLabel: detail.needs_review ? '需要人工复核' : '无需人工复核',
        reviewTone: detail.needs_review ? 'review' : 'passed',
        reviewReasons: detail.review_reasons.map(evaluationReviewReasonLabel),
        metrics,
    };
}

/** Formats a score value while retaining status-only evaluators. */
export function formatEvaluationScore(score: EvaluationScore): string {
    return score.value == null
        ? scoreStatusLabel(score.status)
        : Number.isFinite(score.value)
            ? score.value.toFixed(3)
            : scoreStatusLabel(score.status);
}

/** Formats an annotation without rendering unbounded evidence or comments in collapsed UI. */
export function summarizeEvaluationAnnotation(annotation: { adjudication: boolean; blind: boolean }): string {
    if (annotation.adjudication) return '专家裁决';
    return annotation.blind ? '盲测标注' : '人工标注';
}

function scoreStatusLabel(status: string): string {
    const outcome = evaluationScoreOutcome(status);
    return outcome === 'passed' ? '通过' : outcome === 'failed' ? '未通过' : '待复核';
}

function totalTokenUsage(usage: Record<string, number>): number | null {
    const directTotal = usage.total_tokens ?? usage.total ?? usage.token_total;
    if (typeof directTotal === 'number' && Number.isFinite(directTotal)) return Math.round(directTotal);
    const values = Object.values(usage).filter((value) => Number.isFinite(value) && value >= 0);
    return values.length ? Math.round(values.reduce((total, value) => total + value, 0)) : null;
}

function formatUsd(value: number): string {
    return `$${value.toFixed(value < 0.01 ? 4 : 2)}`;
}
