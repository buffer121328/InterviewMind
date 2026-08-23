import { parseAgentRunTimestamp, RUN_CENTER_TIME_ZONE } from './agentRunPresentation.ts';
import type { AgentModelPerformanceTrendPoint, AgentPerformanceOverview, AgentPerformanceTrendPoint, AgentTaskHealth, AgentTaskHealthIssue, AgentTaskHealthOutcome } from './api/agentRunTypes';

export type TaskHealthSeverity = 'success' | 'warning' | 'danger' | 'neutral';

export interface TaskHealthPresentation {
    businessCategory: string;
    taskLabel: string;
    statusLabel: string;
    severity: TaskHealthSeverity;
    stageLabel: string;
    primaryIssueLabel: string | null;
    disposition: string;
    diagnostics: string[];
}

export interface MetricChartDatum {
    name: string;
    count: number;
}

export interface TaskHealthTrendPoint {
    date: string;
    count: number;
    attention: number;
}

export interface TaskHealthSummary {
    total: number;
    finalSucceeded: number;
    recovered: number;
    failed: number;
    active: number;
    attentionCount: number;
    categoryDistribution: MetricChartDatum[];
    issueDistribution: MetricChartDatum[];
    trend: TaskHealthTrendPoint[];
}

/** A Recharts-ready line series with a readable actual-model legend label. */
export interface ModelCallTrendSeries {
    key: string;
    label: string;
}

/** One date bucket widened into numeric fields for dynamically sized model series. */
export interface ModelCallTrendDatum {
    date: string;
    [seriesKey: string]: string | number;
}

export interface ModelCallTrendChart {
    data: ModelCallTrendDatum[];
    series: ModelCallTrendSeries[];
}

const TASK_LABELS: Record<AgentTaskHealth['task_type'], string> = {
    ability_profile: '能力画像生成',
    evaluation_suite: '评测任务',
    interview_evaluation_draft: '面试评估草稿',
    interview_report: '面试报告',
    interview_scoring: '面试回答评分',
    interview_start: '面试开始',
    interview_turn: '面试回复',
    job_assets: '岗位材料生成',
    job_recommendation_capture: '岗位推荐采集',
    resume_generation: '简历生成',
    resume_optimize: '简历优化',
    resume_workspace: '简历工作台',
    voice_interview_turn: '语音面试回复',
};

const ISSUE_LABELS: Record<AgentTaskHealthIssue, string> = {
    timeout: '模型响应超时',
    authentication: '模型授权异常',
    rate_limit: '模型服务限流',
    network: '网络连接异常',
    request: '请求参数异常',
    model_failure: '模型调用失败',
    skipped: '模型调用已跳过',
    context_protection: '上下文保护已触发',
    fallback: '已切换备用模型',
    retry: '已自动重试',
};

/** Formats an optional rate while preserving the backend's explicit no-data semantics. */
export function formatMetricRate(value: number | null): string {
    return value == null ? '暂无样本' : `${(value * 100).toFixed(1)}%`;
}

/** Formats an optional duration in a compact dashboard representation. */
export function formatMetricDuration(value: number | null): string {
    if (value == null) return '暂无样本';
    return value < 1000 ? `${Math.round(value)}ms` : `${(value / 1000).toFixed(2)}s`;
}

/** Formats a token total without implying a cost estimate. */
export function formatMetricCount(value: number | null): string {
    return value == null ? '暂无样本' : new Intl.NumberFormat('zh-CN').format(Math.max(0, Math.round(value)));
}

/** Explains why a cache hit rate is unavailable instead of presenting unsupported providers as missing telemetry. */
export function formatPromptCacheHitRate(value: AgentPerformanceOverview): string {
    if (value.cache_hit_rate != null) return `${(value.cache_hit_rate * 100).toFixed(1)}%`;
    const counts = value.cache_status_counts;
    const supportedSamples = (counts?.hit ?? 0) + (counts?.miss ?? 0);
    if (supportedSamples > 0) return '等待命中率汇总';
    if ((counts?.unsupported ?? 0) > 0) return '当前模型不支持';
    if ((counts?.unreported ?? 0) > 0) return '供应商未上报';
    return '暂无样本';
}

/** Formats provider-reported prompt-cache outcomes without treating unsupported or unreported calls as misses. */
export function formatPromptCacheStatus(value: AgentPerformanceOverview): string {
    const counts = value.cache_status_counts;
    if (!counts) return '暂无样本';
    const total = (counts.hit ?? 0) + (counts.miss ?? 0) + (counts.unsupported ?? 0) + (counts.unreported ?? 0);
    if (total === 0) return '暂无样本';
    return `命中 ${counts.hit ?? 0} · 未命中 ${counts.miss ?? 0} · 不支持 ${counts.unsupported ?? 0} · 未上报 ${counts.unreported ?? 0}`;
}

/** Keeps all overview charts on the same explicit data-versus-empty-state boundary. */
export function hasPerformanceTrendSamples(trend: readonly AgentPerformanceTrendPoint[] | null | undefined): boolean {
    return Boolean(trend?.length);
}

/** Keeps the named-model chart empty unless the backend returned at least one safe model aggregate. */
export function hasModelCallTrendSamples(trend: readonly AgentModelPerformanceTrendPoint[] | null | undefined): boolean {
    return Boolean(trend?.length);
}

/** Converts raw safe model names into compact, product-facing model legend labels. */
export function formatModelTrendLabel(modelName: string, modelProvider: string | null): string {
    const compactModelName = modelName.replace(/^deepseek-/i, 'ds-');
    const providers = (modelProvider || '')
        .split(',')
        .map((provider) => provider.trim().toLowerCase())
        .filter(Boolean);

    if (providers.includes('volcengine')) {
        const channel = compactModelName.toLowerCase() === 'ds-v4-flash' ? '方舟' : 'volcengine';
        return `${channel}·${compactModelName}`;
    }
    if (providers.some((provider) => provider === 'deepseek' || provider === 'openai_compatible')) {
        return `ds·${compactModelName}`;
    }
    if (providers.length === 0) return compactModelName;

    const fallbackChannel = providers[0].replace(/[._-]+/g, ' ');
    return `${fallbackChannel}·${compactModelName}`;
}

/** Converts safe model aggregates into concise, deterministic Recharts line series. */
export function buildModelCallTrendChart(trend: readonly AgentModelPerformanceTrendPoint[]): ModelCallTrendChart {
    const totalByLabel = new Map<string, number>();
    const pointsByDate = new Map<string, Map<string, number>>();

    for (const point of trend) {
        const label = formatModelTrendLabel(point.model_name, point.model_provider);
        totalByLabel.set(label, (totalByLabel.get(label) || 0) + point.logical_call_count);
        const day = pointsByDate.get(point.date) || new Map<string, number>();
        day.set(label, (day.get(label) || 0) + point.logical_call_count);
        pointsByDate.set(point.date, day);
    }

    const labels = [...totalByLabel.keys()].sort((left, right) => {
        const channelOrder = (label: string) => {
            if (label.startsWith('方舟·')) return 0;
            if (label.startsWith('ds·')) return 1;
            return 2;
        };
        const channelDiff = channelOrder(left) - channelOrder(right);
        if (channelDiff !== 0) return channelDiff;
        const volumeDiff = (totalByLabel.get(right) || 0) - (totalByLabel.get(left) || 0);
        if (volumeDiff !== 0) return volumeDiff;
        return left.localeCompare(right, 'zh-CN');
    });
    const series = labels.map((label, index) => ({ key: `model_${index}`, label }));
    const keysByLabel = new Map(labels.map((label, index) => [label, series[index].key]));
    const data = [...pointsByDate.entries()]
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([date, totals]) => {
            const datum: ModelCallTrendDatum = { date };
            for (const label of labels) {
                datum[keysByLabel.get(label) || label] = totals.get(label) || 0;
            }
            return datum;
        });

    return { data, series };
}

/** Aggregates safe daily retries, fallbacks, and timeouts for the overview health chart. */
export function buildCallHealthChart(
    trend: readonly AgentPerformanceTrendPoint[] | null | undefined,
): MetricChartDatum[] | null {
    const points = trend || [];
    if (points.length === 0) return null;

    return [
        { name: '重试', count: points.reduce((total, point) => total + point.retry_count, 0) },
        { name: '备用模型', count: points.reduce((total, point) => total + point.fallback_count, 0) },
        { name: '超时', count: points.reduce((total, point) => total + point.timeout_count, 0) },
    ];
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
        ['Retry 率', formatMetricRate(value.retry_rate)],
        ['Token 消耗', formatMetricCount(value.total_tokens ?? (value.sample_event_count > 0 ? value.input_tokens + value.output_tokens : null))],
    ] as const;
}

/** Maps a safe internal stage identifier to stable user-facing copy. */
export function getTaskHealthStageLabel(stage: string | null): string {
    if (!stage) return '未标记阶段';
    const normalized = stage.toLowerCase().replace(/[.\-/\s]+/g, '_');
    if (normalized.includes('narrative') || normalized.includes('report')) return '报告撰写';
    if (normalized.includes('rewrite') || normalized.includes('optimiz')) return '简历优化';
    if (normalized.includes('generation') || normalized.includes('generate')) return '内容生成';
    if (normalized.includes('interview')) return '模拟面试处理';
    if (normalized.includes('resume')) return '简历处理';
    if (normalized.includes('job') || normalized.includes('capture')) return '岗位处理';
    if (normalized.includes('evaluation')) return '质量评测';
    if (normalized.includes('memory')) return '长期记忆';
    if (normalized.includes('rag') || normalized.includes('retriev')) return '知识检索';
    return '任务处理';
}

/** Resolves a task's business category without surfacing the implementation-level task type. */
function getBusinessCategory(taskType: AgentTaskHealth['task_type']): string {
    if (taskType === 'voice_interview_turn') return '语音面试';
    if (taskType === 'resume_optimize' || taskType === 'resume_workspace' || taskType === 'resume_generation') return '简历优化';
    if (taskType === 'job_assets' || taskType === 'job_recommendation_capture') return '岗位投递';
    if (taskType === 'ability_profile') return '能力画像';
    if (taskType === 'evaluation_suite') return '质量评测';
    return '文本面试';
}

/** Resolves the stable business-facing label for a model call-chain summary. */
function getTaskLabel(taskType: AgentTaskHealth['task_type']): string {
    return TASK_LABELS[taskType];
}

/** Returns Chinese issue copy without exposing a raw backend failure type. */
export function getTaskHealthIssueLabel(issue: AgentTaskHealthIssue | null): string | null {
    return issue ? ISSUE_LABELS[issue] : null;
}

/** Converts one per-run API summary into content suitable for a product card. */
export function getTaskHealthPresentation(health: AgentTaskHealth): TaskHealthPresentation {
    const businessCategory = getBusinessCategory(health.task_type);
    const primaryIssueLabel = getTaskHealthIssueLabel(health.primary_issue);
    const status: Record<AgentTaskHealthOutcome, { label: string; severity: TaskHealthSeverity }> = {
        succeeded: { label: '正常完成', severity: 'success' },
        recovered: { label: '自动恢复完成', severity: 'warning' },
        failed: { label: '任务失败', severity: 'danger' },
        active: { label: '仍在执行', severity: 'neutral' },
    };
    const diagnostics = [
        health.physical_attempt_count > 1 ? `已记录 ${health.physical_attempt_count} 次模型尝试` : null,
        health.failed_attempt_count > 0 ? `${health.failed_attempt_count} 次尝试未完成` : null,
        health.timeout_count > 0 ? `${health.timeout_count} 次超时` : null,
        health.retry_count > 0 ? `已自动重试 ${health.retry_count} 次` : null,
        health.fallback_count > 0 ? '已切换备用模型' : null,
        health.skipped_count > 0 ? `${health.skipped_count} 次调用被策略跳过` : null,
        health.context_protection_count > 0 ? `${health.context_protection_count} 次上下文保护` : null,
    ].filter((value): value is string => Boolean(value));
    const disposition = health.outcome === 'succeeded'
        ? '任务最终已完成，未记录影响结果的模型异常。'
        : health.outcome === 'recovered'
            ? `任务最终已完成；${primaryIssueLabel || '调用异常'}已由重试或降级策略处理。`
            : health.outcome === 'failed'
                ? `任务最终未完成；${primaryIssueLabel || '模型调用异常'}是当前主要诊断。`
                : health.primary_issue
                    ? `任务仍在执行；已记录${primaryIssueLabel}，可继续观察后续任务结果。`
                    : '任务仍在执行，尚未形成最终调用结论。';

    return {
        businessCategory,
        taskLabel: getTaskLabel(health.task_type),
        statusLabel: status[health.outcome].label,
        severity: status[health.outcome].severity,
        stageLabel: getTaskHealthStageLabel(health.primary_stage || health.stage),
        primaryIssueLabel,
        disposition,
        diagnostics,
    };
}

/** Returns whether a task needs user-facing attention after outcome-level aggregation. */
function needsAttention(health: AgentTaskHealth): boolean {
    return health.outcome === 'recovered' || health.outcome === 'failed' || (health.outcome === 'active' && health.primary_issue != null);
}

/** Groups per-task summaries into task outcomes, root causes, business categories, and daily trend charts. */
export function summarizeTaskHealth(runs: AgentTaskHealth[]): TaskHealthSummary {
    const categories = new Map<string, number>();
    const issues = new Map<string, number>();
    const trend = new Map<string, { date: string; count: number; attention: number }>();
    let finalSucceeded = 0;
    let recovered = 0;
    let failed = 0;
    let active = 0;
    let attentionCount = 0;

    for (const health of runs) {
        const presentation = getTaskHealthPresentation(health);
        categories.set(presentation.businessCategory, (categories.get(presentation.businessCategory) || 0) + 1);
        if (health.task_status === 'succeeded') finalSucceeded += 1;
        if (health.outcome === 'recovered') recovered += 1;
        if (health.outcome === 'failed') failed += 1;
        if (health.outcome === 'active') active += 1;
        const attention = needsAttention(health);
        if (attention) {
            attentionCount += 1;
            const issue = presentation.primaryIssueLabel || '需要进一步观察';
            issues.set(issue, (issues.get(issue) || 0) + 1);
        }
        const timestamp = parseAgentRunTimestamp(health.created_at || health.last_model_event_at);
        const dateParts = timestamp ? new Intl.DateTimeFormat('en-CA', {
            year: 'numeric', month: '2-digit', day: '2-digit', timeZone: RUN_CENTER_TIME_ZONE,
        }).formatToParts(timestamp) : [];
        const datePart = (type: Intl.DateTimeFormatPartTypes) => dateParts.find(part => part.type === type)?.value;
        const key = timestamp ? `${datePart('year')}-${datePart('month')}-${datePart('day')}` : `unknown-${health.run_id}`;
        const date = timestamp
            ? new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', timeZone: RUN_CENTER_TIME_ZONE }).format(timestamp)
            : '时间未记录';
        const point = trend.get(key) || { date, count: 0, attention: 0 };
        point.count += 1;
        if (attention) point.attention += 1;
        trend.set(key, point);
    }

    return {
        total: runs.length,
        finalSucceeded,
        recovered,
        failed,
        active,
        attentionCount,
        categoryDistribution: [...categories.entries()].map(([name, count]) => ({ name, count })),
        issueDistribution: [...issues.entries()].map(([name, count]) => ({ name, count })),
        trend: [...trend.entries()].sort(([left], [right]) => left.localeCompare(right)).map(([, value]) => value),
    };
}
