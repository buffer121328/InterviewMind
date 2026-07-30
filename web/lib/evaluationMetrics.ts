import type { EvaluationOverview, EvaluationRun, EvaluationScore } from './api/evaluations';

export function formatEvaluationRate(value: number | null | undefined): string {
    return value == null || !Number.isFinite(value) ? '样本不足' : `${(value * 100).toFixed(1)}%`;
}

export function formatSignedRate(value: number | null | undefined): string {
    if (value == null || !Number.isFinite(value)) return '无基线';
    const percent = value * 100;
    return `${percent > 0 ? '+' : ''}${percent.toFixed(1)}%`;
}

export function runProgress(run: EvaluationRun): number {
    const value = Number(run.summary.progress ?? 0);
    return Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));
}

export function overviewCards(overview: EvaluationOverview) {
    return [
        { key: 'runtime', label: '运行成功率', value: formatEvaluationRate(overview.runtime_success_rate), tone: 'blue' },
        { key: 'semantic', label: '语义成功率', value: formatEvaluationRate(overview.semantic_success_rate), tone: 'teal' },
        { key: 'complete', label: '完全成功率', value: formatEvaluationRate(overview.complete_success_rate), tone: 'emerald' },
        { key: 'gate', label: '安全门禁通过率', value: formatEvaluationRate(overview.hard_gate_pass_rate), tone: 'violet' },
        { key: 'factual', label: '事实支持率', value: formatEvaluationRate(overview.factual_support_rate), tone: 'cyan' },
        { key: 'tool', label: '工具调用正确率', value: formatEvaluationRate(overview.tool_call_accuracy), tone: 'indigo' },
        { key: 'agreement', label: 'Judge / 人工一致性', value: formatEvaluationRate(overview.judge_human_agreement), tone: 'fuchsia' },
        { key: 'latency', label: '最近 P95 延迟', value: overview.p95_latency_ms == null ? '样本不足' : `${Math.round(overview.p95_latency_ms)} ms`, tone: 'amber' },
        { key: 'token', label: 'Token 相对基线', value: formatSignedRate(overview.token_delta_percent), tone: 'orange' },
        { key: 'review', label: '待人工复核', value: String(overview.pending_review_count), tone: 'rose' },
        { key: 'regression', label: '回归告警', value: String(overview.regression_count), tone: 'red' },
        { key: 'runs', label: '评测运行数', value: String(overview.run_count), tone: 'slate' },
    ] as const;
}

export function groupScoresBySource(scores: EvaluationScore[]): Record<string, EvaluationScore[]> {
    return scores.reduce<Record<string, EvaluationScore[]>>((groups, score) => {
        (groups[score.source] ??= []).push(score);
        return groups;
    }, {});
}
