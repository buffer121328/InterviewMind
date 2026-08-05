import type { AgentPerformanceOverview, ModelMetricEvent } from './api/agentRunTypes';

/** Formats an optional rate while preserving the backend's explicit no-data semantics. */
export function formatMetricRate(value: number | null): string {
    return value == null ? '暂无样本' : `${(value * 100).toFixed(1)}%`;
}

/** Formats an optional duration in a compact dashboard representation. */
export function formatMetricDuration(value: number | null): string {
    if (value == null) return '暂无样本';
    return value < 1000 ? `${Math.round(value)}ms` : `${(value / 1000).toFixed(2)}s`;
}

/** Builds the stable headline cards shared by the performance overview and tests. */
export function performanceCards(value: AgentPerformanceOverview) {
    return [
        ['运行成功率', formatMetricRate(value.run_success_rate)],
        ['模型 P50', formatMetricDuration(value.p50_model_duration_ms)],
        ['模型 P95', formatMetricDuration(value.p95_model_duration_ms)],
        ['调用放大', value.call_amplification == null ? '暂无样本' : `${value.call_amplification.toFixed(2)}x`],
        ['Fallback', formatMetricRate(value.fallback_rate)],
        ['Timeout', formatMetricRate(value.timeout_rate)],
        ['权威截断', formatMetricRate(value.authoritative_truncation_rate)],
        ['Cache Hit', formatMetricRate(value.cache_hit_rate)],
    ] as const;
}

/** Returns a credential-free human explanation for one model metric event. */
export function describeModelMetricEvent(event: ModelMetricEvent): string {
    const payload = event.payload;
    const model = String(payload.model_name || payload.model_member || 'unknown-model');
    const provider = String(payload.model_provider || 'unknown-provider');
    const attempt = Number(payload.attempt || 1);
    const fallback = Number(payload.fallback_index || 0);
    const reason = String(payload.failure_type || payload.error_category || 'normal');
    return `${provider} / ${model} · attempt ${attempt} · fallback ${fallback} · ${reason}`;
}
