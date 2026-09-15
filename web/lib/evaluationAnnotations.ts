import type { EvaluationAnnotation, EvaluationCaseRunDetail } from './api/evaluations';

export type AnnotationState = 'pending' | 'annotated' | 'conflicted' | 'adjudicated' | 'calibration_ready';

export function deriveAnnotationState(items: EvaluationAnnotation[], metricName?: string): AnnotationState {
    const relevant = metricName ? items.filter((item) => item.metric_name === metricName) : items;
    if (!relevant.length) return 'pending';
    if (relevant.some((item) => item.adjudication)) return 'adjudicated';
    const latest = new Map<string, EvaluationAnnotation>();
    for (const item of relevant) latest.set(item.reviewer_key, item);
    if (latest.size < 2) return 'annotated';
    const values = [...latest.values()].map((item) => JSON.stringify(item.value));
    return new Set(values).size === 1 ? 'calibration_ready' : 'conflicted';
}

/** Mirrors the backend confirmed-failure gate for Candidate Dataset promotion. */
export function canPromoteCandidateDataset(detail: EvaluationCaseRunDetail): boolean {
    if (detail.review_status !== 'rejected') return false;
    if (detail.status !== 'succeeded' || !detail.hard_gate_passed) return true;
    return detail.scores.some(score => score.source !== 'human' && score.status === 'failed');
}
