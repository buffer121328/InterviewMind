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
        { key: 'runtime', group: 'quality', label: '运行成功率', value: formatEvaluationRate(overview.runtime_success_rate), tone: 'blue' },
        { key: 'semantic-evaluated', group: 'quality', label: '语义已评测率', value: formatEvaluationRate(overview.semantic_evaluated_rate), tone: 'sky' },
        { key: 'semantic', group: 'quality', label: '语义成功率', value: formatEvaluationRate(overview.semantic_success_rate), tone: 'teal' },
        { key: 'complete', group: 'quality', label: '完全成功率', value: formatEvaluationRate(overview.complete_success_rate), tone: 'emerald' },
        { key: 'factual', group: 'quality', label: '事实支持率', value: formatEvaluationRate(overview.factual_support_rate), tone: 'cyan' },
        { key: 'tool', group: 'quality', label: '工具选择正确率', value: formatEvaluationRate(overview.tool_call_accuracy), tone: 'indigo' },
        { key: 'agreement', group: 'quality', label: 'Judge / 人工一致性', value: formatEvaluationRate(overview.judge_human_agreement), tone: 'fuchsia' },
        { key: 'gate', group: 'governance', label: '安全门禁通过率', value: formatEvaluationRate(overview.hard_gate_pass_rate), tone: 'violet' },
        { key: 'review', group: 'governance', label: '待人工复核', value: String(overview.pending_review_count), tone: 'rose' },
        { key: 'regression', group: 'governance', label: '回归告警', value: String(overview.regression_count), tone: 'red' },
        { key: 'trace', group: 'governance', label: 'Trace 完整率', value: formatEvaluationRate(overview.trace_completeness_rate), tone: 'purple' },
        { key: 'trace-missing', group: 'governance', label: '观测缺失案例', value: String(overview.trace_incomplete_count), tone: 'amber' },
        { key: 'external-effects', group: 'governance', label: 'External 动作', value: String(overview.external_effect_count), tone: 'violet' },
        { key: 'external-blocked', group: 'governance', label: 'External 阻断', value: String(overview.external_effect_blocked_count), tone: 'red' },
        { key: 'approval', group: 'governance', label: '审批证据数', value: String(overview.approval_event_count), tone: 'green' },
        { key: 'approval-violations', group: 'governance', label: '审批违规', value: String(overview.approval_violation_count), tone: 'red' },
        { key: 'latency', group: 'stability', label: '最近 P95 延迟', value: overview.p95_latency_ms == null ? '样本不足' : `${Math.round(overview.p95_latency_ms)} ms`, tone: 'amber' },
        { key: 'token', group: 'stability', label: 'Token 相对基线', value: formatSignedRate(overview.token_delta_percent), tone: 'orange' },
        { key: 'tool-success', group: 'stability', label: '工具执行成功率', value: formatEvaluationRate(overview.tool_execution_success_rate), tone: 'emerald' },
        { key: 'tool-failure', group: 'stability', label: '工具失败率', value: formatEvaluationRate(overview.tool_failure_rate), tone: 'orange' },
        { key: 'tool-blocked', group: 'governance', label: '工具正确阻断率', value: formatEvaluationRate(overview.tool_blocked_rate), tone: 'violet' },
        { key: 'tool-retry', group: 'stability', label: '工具重试率', value: formatEvaluationRate(overview.tool_retry_rate), tone: 'amber' },
        { key: 'tool-duration', group: 'stability', label: 'Tool P95 耗时', value: overview.tool_p95_duration_ms == null ? '样本不足' : `${Math.round(overview.tool_p95_duration_ms)} ms`, tone: 'amber' },
        { key: 'dependency-failure', group: 'stability', label: '依赖失败率', value: formatEvaluationRate(overview.dependency_failure_rate), tone: 'rose' },
        { key: 'dependency-timeout', group: 'stability', label: '外部 IO 超时率', value: formatEvaluationRate(overview.external_io_timeout_rate), tone: 'red' },
        { key: 'retrieval-empty', group: 'stability', label: '检索空召回率', value: formatEvaluationRate(overview.retrieval_empty_rate), tone: 'orange' },
        { key: 'retrieval-success', group: 'quality', label: '检索成功率', value: formatEvaluationRate(overview.retrieval_success_rate), tone: 'cyan' },
        { key: 'retrieval-adopted', group: 'quality', label: '检索采用率', value: formatEvaluationRate(overview.retrieval_adopted_rate), tone: 'teal' },
        { key: 'memory-hit', group: 'quality', label: 'Memory 命中率', value: formatEvaluationRate(overview.memory_search_hit_rate), tone: 'cyan' },
        { key: 'memory-adopted', group: 'quality', label: 'Memory 采用率', value: formatEvaluationRate(overview.memory_adopted_rate), tone: 'teal' },
        { key: 'memory-duplicate', group: 'governance', label: 'Memory 重复写率', value: formatEvaluationRate(overview.memory_write_duplication_rate), tone: 'rose' },
        { key: 'langfuse-reported', group: 'observability', label: 'Langfuse 已上报案例', value: String(overview.langfuse_reported_case_count), tone: 'cyan' },
        { key: 'langfuse-failed', group: 'observability', label: 'Langfuse 降级案例', value: String(overview.langfuse_failed_case_count), tone: 'amber' },
        { key: 'runs', group: 'observability', label: '评测运行数', value: String(overview.run_count), tone: 'slate' },
    ] as const;
}

export function groupScoresBySource(scores: EvaluationScore[]): Record<string, EvaluationScore[]> {
    return scores.reduce<Record<string, EvaluationScore[]>>((groups, score) => {
        (groups[score.source] ??= []).push(score);
        return groups;
    }, {});
}
