import type { EvaluationRun } from './api/evaluations';

export const RECENT_EVALUATION_MAX_ITEMS = 10;
export const RECENT_EVALUATION_PAGE_SIZE = 5;

export type EvaluationRunMode = 'quick' | 'standard' | 'release' | 'other';

export type RecentEvaluationResultItem =
    | { kind: 'run'; id: string; run: EvaluationRun }
    | { kind: 'batch'; id: string; batchId: string; runs: EvaluationRun[] };

/** Converts the ordered run response into ten user-facing records, grouping every smoke batch once. */
export function recentEvaluationResultItems(
    runs: EvaluationRun[],
    selectedAgentName: string | null,
): RecentEvaluationResultItem[] {
    const seenBatchIds = new Set<string>();
    const items: RecentEvaluationResultItem[] = [];

    for (const run of runs) {
        if (run.smoke_batch_id) {
            if (seenBatchIds.has(run.smoke_batch_id)) continue;
            seenBatchIds.add(run.smoke_batch_id);
            items.push({
                kind: 'batch',
                id: `batch:${run.smoke_batch_id}`,
                batchId: run.smoke_batch_id,
                runs: runs.filter(item => item.smoke_batch_id === run.smoke_batch_id),
            });
        } else if (!selectedAgentName || run.agent_name === selectedAgentName) {
            items.push({ kind: 'run', id: run.id, run });
        }

        if (items.length === RECENT_EVALUATION_MAX_ITEMS) break;
    }

    return items;
}

/** Returns a stable five-item page from the fixed recent-result window. */
export function recentEvaluationResultPage(
    items: RecentEvaluationResultItem[],
    page: number,
): RecentEvaluationResultItem[] {
    const safePage = Math.max(1, page);
    const start = (safePage - 1) * RECENT_EVALUATION_PAGE_SIZE;
    return items.slice(start, start + RECENT_EVALUATION_PAGE_SIZE);
}

/** Maps persisted quick-evaluation context to a user-facing assessment category. */
export function evaluationRunMode(run: EvaluationRun): EvaluationRunMode {
    const persistedMode = run.budget.mode;
    if (persistedMode === 'quick' || persistedMode === 'standard' || persistedMode === 'release') {
        return persistedMode;
    }
    if (run.smoke_batch_id || run.budget.max_cases === 1) return 'quick';
    const datasetName = run.dataset_version.split(':', 1)[0] ?? '';
    if (datasetName.endsWith('.release')) return 'release';
    if (datasetName.endsWith('.standard')) return 'standard';
    return 'other';
}

/** Uses the same labels in top-level items, batch summaries, and child run rows. */
export function evaluationRunModeLabel(run: EvaluationRun): string {
    return ({
        quick: '快速冒烟',
        standard: '标准回归',
        release: '发布检查',
        other: '评测运行',
    } as const)[evaluationRunMode(run)];
}

/** Produces one summary status for a smoke batch without hiding an in-flight child. */
export function evaluationBatchStatus(runs: EvaluationRun[]): string {
    if (runs.some(run => run.status === 'running' || run.status === 'queued')) return 'running';
    if (runs.some(run => run.status === 'failed')) return 'failed';
    if (runs.every(run => run.status === 'succeeded')) return 'succeeded';
    if (runs.every(run => run.status === 'cancelled')) return 'cancelled';
    return runs[0]?.status ?? 'queued';
}
