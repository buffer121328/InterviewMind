import type { EvaluationAnnotation } from './api/evaluations';

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
