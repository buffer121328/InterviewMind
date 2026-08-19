'use client';

import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { AlertTriangle, CheckCircle2, ChevronDown, ExternalLink, Info, RefreshCw, ShieldCheck, TimerReset } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { PaginationControls } from '@/components/PaginationControls';
import { getAgentPerformanceOverview, getAgentRunTraceLink, listAgentTaskHealth } from '@/lib/api/agentRuns';
import type { AgentModelPerformanceTrendPoint, AgentPerformanceOverview, AgentPerformanceTrendPoint, AgentTaskHealth } from '@/lib/api/agentRunTypes';
import { DEFAULT_PAGE_SIZE } from '@/lib/pagination';
import { parseAgentRunTimestamp, RUN_CENTER_TIME_ZONE } from '@/lib/agentRunPresentation';
import {
    buildCallHealthChart,
    buildModelCallTrendChart,
    formatModelTrendLabel,
    formatPromptCacheHitRate,
    formatPromptCacheStatus,
    getTaskHealthPresentation,
    hasModelCallTrendSamples,
    hasPerformanceTrendSamples,
    performanceCards,
    summarizeTaskHealth,
    type TaskHealthPresentation,
    type TaskHealthSummary,
} from '@/lib/agentPerformance';
import { toast } from 'sonner';

interface PerformanceViewProps {
    /** Selects the backend performance window; the value is bounded again server-side. */
    days: number;
}

const CHART_COLORS = ['#14b8a6', '#6366f1', '#f43f5e', '#f59e0b', '#38bdf8', '#f97316', '#94a3b8'];
const ALL_MODELS_VALUE = '__all_models__';
const TASK_PAGE_SIZE = DEFAULT_PAGE_SIZE;
const EMPTY_PERFORMANCE_TREND: AgentPerformanceTrendPoint[] = [];
const EMPTY_MODEL_TREND: AgentModelPerformanceTrendPoint[] = [];

/** Opens an owner-validated Langfuse link without synthesizing URLs in the browser. */
async function openTrace(runId: string) {
    try {
        const link = await getAgentRunTraceLink(runId);
        if (!link.available || !link.url) {
            toast.info(link.message || '当前任务没有可用 Trace');
            return;
        }
        window.open(link.url, '_blank', 'noopener,noreferrer');
    } catch (error) {
        toast.error(error instanceof Error ? error.message : 'Trace 打开失败');
    }
}

/** Renders aggregate performance indicators with safe daily volume and stability trends. */
export function PerformanceOverviewTab({ days }: PerformanceViewProps) {
    const [value, setValue] = useState<AgentPerformanceOverview | null>(null);
    const [selectedModelName, setSelectedModelName] = useState<string | undefined>();
    const [loading, setLoading] = useState(true);
    const load = useCallback(async () => {
        setLoading(true);
        try {
            setValue(await getAgentPerformanceOverview({ days, modelName: selectedModelName }));
        } catch (error) {
            toast.error(error instanceof Error ? error.message : '性能指标加载失败');
        } finally {
            setLoading(false);
        }
    }, [days, selectedModelName]);
    useEffect(() => { queueMicrotask(() => void load()); }, [load]);

    const cards = useMemo(() => value ? performanceCards(value) : [], [value]);
    const trend = value?.daily_trend ?? EMPTY_PERFORMANCE_TREND;
    const modelTrend = value?.model_daily_trend ?? EMPTY_MODEL_TREND;
    const modelTrendChart = useMemo(() => buildModelCallTrendChart(modelTrend), [modelTrend]);
    const hasTrend = hasPerformanceTrendSamples(trend);
    const hasModelTrend = hasModelCallTrendSamples(modelTrend);
    const callHealthChart = useMemo(() => buildCallHealthChart(trend), [trend]);
    const modelOptions = value?.available_models || [];
    const changeModel = (nextValue: string) => {
        setValue(null);
        setSelectedModelName(nextValue === ALL_MODELS_VALUE ? undefined : nextValue);
    };
    if (loading && !value) return <EmptyState text="正在汇总性能指标…" />;
    if (!value || value.sample_event_count === 0) return <EmptyState text="当前窗口暂无性能指标；历史运行不会被填充为虚构数据。" onRefresh={load} />;

    return <div className="space-y-5">
        <section className="overflow-hidden rounded-3xl border border-slate-200 bg-gradient-to-br from-white via-white to-indigo-50/60 shadow-sm shadow-slate-200/40">
            <header className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-100 px-4 py-5 sm:px-5">
                <div className="flex items-start gap-3">
                    <span className="flex h-10 w-10 items-center justify-center rounded-2xl bg-indigo-100 text-indigo-700"><ShieldCheck className="h-5 w-5" aria-hidden="true" /></span>
                    <div>
                        <h2 className="text-base font-semibold text-slate-950">性能总览</h2>
                        <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-600">按任务最终结果和安全模型指标汇总调用规模、延迟与稳定性；趋势均按中国标准时间分日统计。</p>
                    </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    {modelOptions.length > 0 && <Select value={selectedModelName || ALL_MODELS_VALUE} onValueChange={changeModel}>
                        <SelectTrigger className="h-9 w-[240px] bg-white text-sm"><SelectValue placeholder="筛选模型" /></SelectTrigger>
                        <SelectContent>
                            <SelectItem value={ALL_MODELS_VALUE}>全部模型</SelectItem>
                            {modelOptions.map((model) => <SelectItem key={model.model_name} value={model.model_name}>
                                {formatModelTrendLabel(model.model_name, model.model_provider)}
                            </SelectItem>)}
                        </SelectContent>
                    </Select>}
                    <Button variant="outline" size="sm" disabled={loading} onClick={() => void load()}><RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />刷新数据</Button>
                </div>
            </header>
            <div className="p-4 sm:p-5">
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{cards.map(([label, content]) => <HealthMetric key={label} label={label} value={content} tone="neutral" />)}</div>
            </div>
        </section>

        <div className="grid gap-4 xl:grid-cols-2">
            <ChartPanel title="调用量趋势" description="对比每天的逻辑调用与实际 Provider 请求，帮助识别重试、降级造成的调用放大。">
                {hasTrend ? <ResponsiveContainer width="100%" height={270}>
                    <LineChart data={trend} margin={{ top: 10, right: 8, left: -18, bottom: 0 }}>
                        <CartesianGrid vertical={false} stroke="#e2e8f0" strokeDasharray="3 3" />
                        <XAxis dataKey="date" tickFormatter={formatTrendDay} axisLine={false} tickLine={false} tick={{ fill: '#64748b', fontSize: 11 }} />
                        <YAxis allowDecimals={false} axisLine={false} tickLine={false} tick={{ fill: '#64748b', fontSize: 11 }} />
                        <Tooltip contentStyle={tooltipStyle} labelFormatter={(label) => `日期：${formatTrendDay(String(label))}`} />
                        <Legend wrapperStyle={{ fontSize: 12 }} />
                        <Line type="monotone" dataKey="logical_call_count" name="逻辑调用" stroke="#14b8a6" strokeWidth={2.5} dot={{ r: 3 }} activeDot={{ r: 5 }} />
                        <Line type="monotone" dataKey="physical_request_count" name="实际请求" stroke="#6366f1" strokeWidth={2.5} dot={{ r: 3 }} activeDot={{ r: 5 }} />
                    </LineChart>
                </ResponsiveContainer> : <ChartEmpty text="当前窗口尚无可按日汇总的调用记录。" />}
            </ChartPanel>
            <ChartPanel title="稳定性趋势" description="按天查看 P95 响应时延、重试、备用模型和超时；延迟与次数分别使用左右坐标轴。">
                {hasTrend ? <ResponsiveContainer width="100%" height={270}>
                    <LineChart data={trend} margin={{ top: 10, right: 14, left: 12, bottom: 0 }}>
                        <CartesianGrid vertical={false} stroke="#e2e8f0" strokeDasharray="3 3" />
                        <XAxis dataKey="date" tickFormatter={formatTrendDay} axisLine={false} tickLine={false} tick={{ fill: '#64748b', fontSize: 11 }} />
                        <YAxis yAxisId="latency" width={58} tickFormatter={(value) => `${value}ms`} axisLine={false} tickLine={false} tick={{ fill: '#64748b', fontSize: 11 }} />
                        <YAxis yAxisId="count" orientation="right" width={30} allowDecimals={false} axisLine={false} tickLine={false} tick={{ fill: '#64748b', fontSize: 11 }} />
                        <Tooltip contentStyle={tooltipStyle} labelFormatter={(label) => `日期：${formatTrendDay(String(label))}`} />
                        <Legend wrapperStyle={{ fontSize: 12 }} />
                        <Line yAxisId="latency" type="monotone" dataKey="p95_model_duration_ms" name="P95 响应" stroke="#6366f1" strokeWidth={2.5} connectNulls={false} dot={{ r: 3 }} activeDot={{ r: 5 }} />
                        <Line yAxisId="count" type="monotone" dataKey="retry_count" name="重试" stroke="#f59e0b" strokeWidth={2.25} dot={{ r: 3 }} activeDot={{ r: 5 }} />
                        <Line yAxisId="count" type="monotone" dataKey="fallback_count" name="Fallback" stroke="#14b8a6" strokeWidth={2.25} dot={{ r: 3 }} activeDot={{ r: 5 }} />
                        <Line yAxisId="count" type="monotone" dataKey="timeout_count" name="超时" stroke="#f43f5e" strokeWidth={2.25} dot={{ r: 3 }} activeDot={{ r: 5 }} />
                    </LineChart>
                </ResponsiveContainer> : <ChartEmpty text="当前窗口尚无可按日汇总的稳定性记录。" />}
            </ChartPanel>
            <ChartPanel title="Token 消耗趋势" description="按天对比已记录的输入与输出 Token；字段未上报时不会补写为虚构消耗。">
                {hasTrend ? <ResponsiveContainer width="100%" height={270}>
                    <AreaChart data={trend} margin={{ top: 10, right: 8, left: -18, bottom: 0 }}>
                        <defs>
                            <linearGradient id="overviewInputTokens" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="#38bdf8" stopOpacity={0.34} /><stop offset="100%" stopColor="#38bdf8" stopOpacity={0.03} /></linearGradient>
                            <linearGradient id="overviewOutputTokens" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="#8b5cf6" stopOpacity={0.34} /><stop offset="100%" stopColor="#8b5cf6" stopOpacity={0.03} /></linearGradient>
                        </defs>
                        <CartesianGrid vertical={false} stroke="#e2e8f0" strokeDasharray="3 3" />
                        <XAxis dataKey="date" tickFormatter={formatTrendDay} axisLine={false} tickLine={false} tick={{ fill: '#64748b', fontSize: 11 }} />
                        <YAxis allowDecimals={false} axisLine={false} tickLine={false} tick={{ fill: '#64748b', fontSize: 11 }} />
                        <Tooltip contentStyle={tooltipStyle} labelFormatter={(label) => `日期：${formatTrendDay(String(label))}`} />
                        <Legend wrapperStyle={{ fontSize: 12 }} />
                        <Area type="monotone" dataKey="input_tokens" name="输入 Token" stroke="#38bdf8" strokeWidth={2.5} fill="url(#overviewInputTokens)" />
                        <Area type="monotone" dataKey="output_tokens" name="输出 Token" stroke="#8b5cf6" strokeWidth={2.5} fill="url(#overviewOutputTokens)" />
                    </AreaChart>
                </ResponsiveContainer> : <ChartEmpty text="当前窗口尚无可按日汇总的 Token 消耗记录。" />}
            </ChartPanel>
            <ChartPanel title="按模型调用趋势" description={selectedModelName ? '当前选择的模型会同步筛选全部主指标和趋势。' : '按逻辑调用量展示前 5 个实际模型名；其余模型合并为“其他模型”。'}>
                {hasModelTrend ? <ResponsiveContainer width="100%" height={270}>
                    <LineChart data={modelTrendChart.data} margin={{ top: 10, right: 8, left: -18, bottom: 0 }}>
                        <CartesianGrid vertical={false} stroke="#e2e8f0" strokeDasharray="3 3" />
                        <XAxis dataKey="date" tickFormatter={formatTrendDay} axisLine={false} tickLine={false} tick={{ fill: '#64748b', fontSize: 11 }} />
                        <YAxis allowDecimals={false} axisLine={false} tickLine={false} tick={{ fill: '#64748b', fontSize: 11 }} />
                        <Tooltip contentStyle={tooltipStyle} labelFormatter={(label) => `日期：${formatTrendDay(String(label))}`} />
                        <Legend align="right" verticalAlign="top" height={64} wrapperStyle={{ fontSize: 12, lineHeight: '20px', paddingLeft: 20 }} />
                        {modelTrendChart.series.map((series, index) => <Line key={series.key} type="monotone" dataKey={series.key} name={series.label} stroke={CHART_COLORS[index % CHART_COLORS.length]} strokeWidth={2.5} dot={{ r: 3 }} activeDot={{ r: 5 }} />)}
                    </LineChart>
                </ResponsiveContainer> : <ChartEmpty text="当前窗口尚无带模型名的调用记录。" />}
            </ChartPanel>
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
            <ChartPanel title="调用效率" description="模型用量和重试口径基于安全聚合，不读取模型输入或输出正文。">
                <dl className="grid grid-cols-2 gap-3 text-sm"><Metric label="逻辑调用" value={value.logical_call_count} /><Metric label="实际请求" value={value.physical_request_count} /><Metric label="输入 Token" value={value.input_tokens} /><Metric label="输出 Token" value={value.output_tokens} /><Metric label="总 Token" value={value.total_tokens ?? '暂无样本'} /><Metric label="缓存命中率" value={formatPromptCacheHitRate(value)} /><Metric label="缓存状态" value={formatPromptCacheStatus(value)} /><Metric label="Retry 率" value={value.retry_rate == null ? '暂无样本' : `${(value.retry_rate * 100).toFixed(1)}%`} /></dl>
            </ChartPanel>
            <ChartPanel title="调用异常与恢复" description="汇总当前窗口的重试、备用模型与超时次数；仅在有按日调用样本时展示。">
                {callHealthChart ? <ResponsiveContainer width="100%" height={224}>
                    <BarChart data={callHealthChart} layout="vertical" margin={{ top: 4, right: 18, left: 8, bottom: 0 }}>
                        <CartesianGrid horizontal={false} stroke="#e2e8f0" strokeDasharray="3 3" />
                        <XAxis type="number" allowDecimals={false} axisLine={false} tickLine={false} tick={{ fill: '#64748b', fontSize: 11 }} />
                        <YAxis type="category" dataKey="name" width={66} axisLine={false} tickLine={false} tick={{ fill: '#475569', fontSize: 12 }} />
                        <Tooltip contentStyle={tooltipStyle} formatter={(count) => [`${count} 次`, '次数']} />
                        <Bar dataKey="count" name="次数" fill="#6366f1" radius={[0, 8, 8, 0]} barSize={24} />
                    </BarChart>
                </ResponsiveContainer> : <ChartEmpty text="当前窗口尚无可按日汇总的调用健康记录。" />}
            </ChartPanel>
        </div>
        <p className="px-1 text-xs text-slate-500">口径：逻辑调用 = 首个主候选的 attempt 1；实际请求 = 每一次 Provider started 请求。样本事件 {value.sample_event_count}。</p>
    </div>;
}

/** Renders one product-facing task summary per business task, never a raw event stream. */
export function ModelCallsTab({ days }: PerformanceViewProps) {
    return <TaskHealthList key={`models-${days}`} days={days} attentionOnly={false} empty="当前窗口暂无包含模型调用的任务。" />;
}

/** Renders only tasks whose final result failed or needed recovery/attention. */
export function DegradationsTab({ days }: PerformanceViewProps) {
    return <TaskHealthList key={`degradations-${days}`} days={days} attentionOnly empty="当前窗口没有需要关注的任务。" />;
}

/** Loads owner-scoped task health and pages only product task cards at ten records per page. */
function TaskHealthList({ days, attentionOnly, empty }: PerformanceViewProps & { attentionOnly: boolean; empty: string }) {
    const [runs, setRuns] = useState<AgentTaskHealth[]>([]);
    const [summaryRuns, setSummaryRuns] = useState<AgentTaskHealth[]>([]);
    const [total, setTotal] = useState(0);
    const [page, setPage] = useState(1);
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState<string | null>(null);

    const load = useCallback(async () => {
        setLoading(true);
        setLoadError(null);
        try {
            const [pageResponse, summaryResponse] = await Promise.all([
                listAgentTaskHealth({ days, attentionOnly, limit: TASK_PAGE_SIZE, offset: (page - 1) * TASK_PAGE_SIZE }),
                listAgentTaskHealth({ days, attentionOnly, limit: 500 }),
            ]);
            if (pageResponse.total > 0 && (page - 1) * TASK_PAGE_SIZE >= pageResponse.total) {
                setPage(1);
                return;
            }
            setRuns(pageResponse.runs);
            setSummaryRuns(summaryResponse.runs);
            setTotal(pageResponse.total);
        } catch (error) {
            const message = error instanceof Error ? error.message : '任务加载失败';
            setLoadError(message);
            toast.error(message);
        } finally {
            setLoading(false);
        }
    }, [days, attentionOnly, page]);
    useEffect(() => { queueMicrotask(() => void load()); }, [load]);

    const summary = useMemo(() => summarizeTaskHealth(summaryRuns), [summaryRuns]);
    if (loading && total === 0 && runs.length === 0) return <EmptyState text="正在汇总任务…" />;
    if (total === 0 && !loading) return <EmptyState text={loadError ? `加载失败：${loadError}` : empty} onRefresh={load} />;

    return <div className="space-y-5">
        {loadError && <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"><span>已保留上一次的任务诊断；最新刷新失败：{loadError}</span><Button variant="outline" size="sm" onClick={() => void load()}><RefreshCw className="mr-1.5 h-3.5 w-3.5" />重试</Button></div>}
        <TaskHealthDashboard summary={summary} attentionOnly={attentionOnly} onRefresh={load} loading={loading} />
        <section className="overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm shadow-slate-200/40">
            <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-4 py-4 sm:px-5">
                <div>
                    <h3 className="text-sm font-semibold text-slate-950">任务</h3>
                    <p className="mt-1 text-xs text-slate-500">每项代表一个业务任务的最终结果；仅保留影响结果的模型诊断，不显示原始遥测流水。</p>
                </div>
                <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">共 {total} 个任务</span>
            </header>
            <div className="divide-y divide-slate-100">{runs.map(run => <TaskHealthCard key={run.run_id} health={run} />)}</div>
            <footer className="border-t border-slate-100 px-4 py-3 sm:px-5"><PaginationControls page={page} total={total} pageSize={TASK_PAGE_SIZE} onPageChange={setPage} loading={loading} /></footer>
        </section>
    </div>;
}

/** Shows outcome-level metrics and task-count charts for the matching product summaries. */
function TaskHealthDashboard({ summary, attentionOnly, onRefresh, loading }: { summary: TaskHealthSummary; attentionOnly: boolean; onRefresh: () => void; loading: boolean }) {
    const primaryDistribution = attentionOnly ? summary.issueDistribution : summary.categoryDistribution;
    const distributionTitle = attentionOnly ? '主要异常原因' : '业务任务归属';
    const distributionDescription = attentionOnly
        ? '按需要关注的任务数量统计，每个任务只计入一个最主要的已记录原因。'
        : '按包含模型调用的业务任务统计，不把提示词、embedding 或物理请求事件计入。';
    const metrics = attentionOnly
        ? [
            { label: '需要关注', value: summary.attentionCount, tone: 'warning' as const },
            { label: '最终失败', value: summary.failed, tone: 'danger' as const },
            { label: '自动恢复', value: summary.recovered, tone: 'info' as const },
            { label: '仍在执行', value: summary.active, tone: 'neutral' as const },
        ]
        : [
            { label: '任务最终完成', value: summary.finalSucceeded, tone: 'success' as const },
            { label: '其中自动恢复', value: summary.recovered, tone: 'warning' as const },
            { label: '最终失败', value: summary.failed, tone: 'danger' as const },
            { label: '仍在执行', value: summary.active, tone: 'neutral' as const },
        ];

    return <section className="overflow-hidden rounded-3xl border border-slate-200 bg-gradient-to-br from-white via-white to-teal-50/50 shadow-sm shadow-slate-200/40">
        <header className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-100 px-4 py-5 sm:px-5">
            <div className="flex min-w-0 items-start gap-3">
                <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl ${attentionOnly ? 'bg-amber-100 text-amber-700' : 'bg-teal-100 text-teal-700'}`}>
                    {attentionOnly ? <AlertTriangle className="h-5 w-5" aria-hidden="true" /> : <ShieldCheck className="h-5 w-5" aria-hidden="true" />}
                </div>
                <div>
                    <h2 className="text-base font-semibold text-slate-950">{attentionOnly ? '异常与降级定位' : '任务健康'}</h2>
                    <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-600">成功以任务最终状态计算；出现超时后仍完成的任务会标为自动恢复，不会被当作失败。</p>
                </div>
            </div>
            <Button variant="outline" size="sm" disabled={loading} onClick={() => void onRefresh()}><RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />刷新数据</Button>
        </header>
        <div className="p-4 sm:p-5">
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{metrics.map(metric => <HealthMetric key={metric.label} {...metric} />)}</div>
            <div className="mt-5 grid gap-4 xl:grid-cols-2">
                <ChartPanel title={distributionTitle} description={distributionDescription}>
                    {primaryDistribution.length > 0 ? <><ResponsiveContainer width="100%" height={250}>
                        <PieChart>
                            <Pie data={primaryDistribution} dataKey="count" nameKey="name" innerRadius={58} outerRadius={88} paddingAngle={4} strokeWidth={0}>
                                {primaryDistribution.map((item, index) => <Cell key={item.name} fill={CHART_COLORS[index % CHART_COLORS.length]} />)}
                            </Pie>
                            <Tooltip contentStyle={tooltipStyle} />
                        </PieChart>
                    </ResponsiveContainer><ChartLegend data={primaryDistribution} /></> : <ChartEmpty text="当前任务没有可展示的分类统计。" />}
                </ChartPanel>
                <ChartPanel title="任务记录趋势" description="展示每天的任务数量和其中需要关注的任务数量；不会用缺失的遥测补写结果。">
                    {summary.trend.length > 0 ? <ResponsiveContainer width="100%" height={250}>
                        <AreaChart data={summary.trend} margin={{ top: 10, right: 10, left: -18, bottom: 0 }}>
                            <defs>
                                <linearGradient id="taskHealthCount" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="#14b8a6" stopOpacity={0.35} /><stop offset="100%" stopColor="#14b8a6" stopOpacity={0.02} /></linearGradient>
                                <linearGradient id="taskHealthAttention" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="#f59e0b" stopOpacity={0.35} /><stop offset="100%" stopColor="#f59e0b" stopOpacity={0.02} /></linearGradient>
                            </defs>
                            <CartesianGrid vertical={false} stroke="#e2e8f0" strokeDasharray="3 3" />
                            <XAxis dataKey="date" axisLine={false} tickLine={false} tick={{ fill: '#64748b', fontSize: 11 }} />
                            <YAxis allowDecimals={false} axisLine={false} tickLine={false} tick={{ fill: '#64748b', fontSize: 11 }} />
                            <Tooltip contentStyle={tooltipStyle} />
                            <Area type="monotone" dataKey="count" name="任务" stroke="#14b8a6" strokeWidth={2.5} fill="url(#taskHealthCount)" />
                            <Area type="monotone" dataKey="attention" name="需要关注" stroke="#f59e0b" strokeWidth={2.5} fill="url(#taskHealthAttention)" />
                        </AreaChart>
                    </ResponsiveContainer> : <ChartEmpty text="当前任务没有可按日期展示的记录。" />}
                </ChartPanel>
            </div>
        </div>
    </section>;
}

/** Renders a bounded, task-oriented diagnostics card. */
function TaskHealthCard({ health }: { health: AgentTaskHealth }) {
    const presentation = getTaskHealthPresentation(health);
    return <details className="group px-4 py-4 sm:px-5">
        <summary className="cursor-pointer list-none">
            <div className="flex min-w-0 items-start justify-between gap-3">
                <div className="flex min-w-0 items-start gap-3">
                    <OutcomeIcon presentation={presentation} />
                    <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                            <h4 className="text-sm font-semibold text-slate-900">{presentation.taskLabel}</h4>
                            <StatusBadge presentation={presentation} />
                            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600">{presentation.businessCategory}</span>
                            {presentation.primaryIssueLabel && <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-800">{presentation.primaryIssueLabel}</span>}
                        </div>
                        <p className="mt-1 truncate text-xs text-slate-500">{presentation.stageLabel} · {formatTaskTime(health.finished_at || health.last_model_event_at || health.created_at)}</p>
                    </div>
                </div>
                <ChevronDown className="h-4 w-4 shrink-0 text-slate-400 transition-transform group-open:rotate-180" aria-hidden="true" />
            </div>
        </summary>
        <div className="ml-0 mt-4 grid gap-4 border-t border-slate-100 pt-4 sm:ml-12 lg:grid-cols-[minmax(0,1fr)_auto]">
            <div>
                <p className="text-sm leading-6 text-slate-700">{presentation.disposition}</p>
                <div className="mt-3 flex flex-wrap gap-2">
                    <DiagnosticTag label={`业务：${presentation.businessCategory}`} />
                    <DiagnosticTag label={`阶段：${presentation.stageLabel}`} />
                    {presentation.primaryIssueLabel && <DiagnosticTag label={`主要原因：${presentation.primaryIssueLabel}`} emphasis={presentation.severity === 'danger'} />}
                    {presentation.diagnostics.length > 0 ? presentation.diagnostics.map(diagnostic => <DiagnosticTag key={diagnostic} label={diagnostic} emphasis={presentation.severity === 'danger'} />) : <DiagnosticTag label="未记录影响结果的模型异常" />}
                </div>
                <dl className="mt-4 grid gap-2 text-xs text-slate-500 sm:grid-cols-2">
                    <div className="rounded-xl bg-slate-50 px-3 py-2"><dt>最后模型记录</dt><dd className="mt-1 font-medium text-slate-700">{formatTaskTime(health.last_model_event_at)}</dd></div>
                    <div className="rounded-xl bg-slate-50 px-3 py-2"><dt>任务运行 ID</dt><dd className="mt-1 break-all font-mono text-[11px] text-slate-700" title={health.run_id}>{health.run_id}</dd></div>
                </dl>
            </div>
            <div className="flex items-start justify-end">
                <Button variant="outline" size="sm" onClick={(click) => { click.preventDefault(); void openTrace(health.run_id); }}><ExternalLink className="mr-1.5 h-3.5 w-3.5" />查看 Trace</Button>
            </div>
        </div>
    </details>;
}

/** Shows one compact task-count statistic with a distinct attention tone. */
function HealthMetric({ label, value, tone }: { label: string; value: string | number; tone: 'success' | 'warning' | 'danger' | 'info' | 'neutral' }) {
    const className = {
        success: 'border-teal-100 bg-teal-50/70 text-teal-800',
        warning: 'border-amber-100 bg-amber-50/70 text-amber-800',
        danger: 'border-rose-100 bg-rose-50/70 text-rose-800',
        info: 'border-indigo-100 bg-indigo-50/70 text-indigo-800',
        neutral: 'border-slate-200 bg-slate-50 text-slate-700',
    }[tone];
    return <div className={`rounded-2xl border px-4 py-3 ${className}`}><div className="text-xs font-medium opacity-80">{label}</div><div className="mt-2 text-2xl font-semibold leading-none">{value}</div></div>;
}

/** Provides consistent visual framing for a compact Recharts view. */
function ChartPanel({ title, description, children }: { title: string; description: string; children: ReactNode }) {
    return <section className="min-w-0 rounded-2xl border border-slate-200 bg-white p-4 sm:p-5"><h3 className="text-sm font-semibold text-slate-900">{title}</h3><p className="mt-1 min-h-10 text-xs leading-5 text-slate-500">{description}</p><div className="mt-2">{children}</div></section>;
}

/** Prevents blank charts from looking like an all-zero historical series. */
function ChartEmpty({ text }: { text: string }) {
    return <div className="flex h-[250px] items-center justify-center rounded-xl border border-dashed border-slate-200 bg-slate-50 px-6 text-center text-sm text-slate-500">{text}</div>;
}

/** Makes chart categories readable without relying on hover-only labels. */
function ChartLegend({ data }: { data: { name: string; count: number }[] }) {
    return <div className="mt-1 grid gap-2 text-xs sm:grid-cols-2">{data.map((item, index) => <div key={item.name} className="flex min-w-0 items-center justify-between gap-2 rounded-lg bg-slate-50 px-2.5 py-2"><span className="flex min-w-0 items-center gap-2"><span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: CHART_COLORS[index % CHART_COLORS.length] }} /><span className="truncate text-slate-600">{item.name}</span></span><strong className="text-slate-900">{item.count}</strong></div>)}</div>;
}

/** Renders an accessible text status alongside the severity color. */
function StatusBadge({ presentation }: { presentation: TaskHealthPresentation }) {
    const className = presentation.severity === 'danger' ? 'bg-rose-100 text-rose-700'
        : presentation.severity === 'warning' ? 'bg-amber-100 text-amber-800'
            : presentation.severity === 'success' ? 'bg-teal-100 text-teal-700'
                : 'bg-slate-100 text-slate-600';
    return <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${className}`}>{presentation.statusLabel}</span>;
}

/** Adds a skimmable visual cue without implying that a recovered task failed. */
function OutcomeIcon({ presentation }: { presentation: TaskHealthPresentation }) {
    const className = presentation.severity === 'danger' ? 'bg-rose-100 text-rose-700'
        : presentation.severity === 'warning' ? 'bg-amber-100 text-amber-700'
            : presentation.severity === 'success' ? 'bg-teal-100 text-teal-700'
                : 'bg-slate-100 text-slate-500';
    const Icon = presentation.severity === 'danger' ? AlertTriangle
        : presentation.statusLabel === '自动恢复完成' ? TimerReset
            : presentation.statusLabel === '仍在执行' ? Info : CheckCircle2;
    return <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${className}`}><Icon className="h-4 w-4" aria-hidden="true" /></span>;
}

/** Renders a bounded safe diagnostic tag. */
function DiagnosticTag({ label, emphasis = false }: { label: string; emphasis?: boolean }) {
    return <span className={`rounded-full border px-2.5 py-1 text-[11px] font-medium ${emphasis ? 'border-rose-200 bg-rose-50 text-rose-700' : 'border-slate-200 bg-slate-50 text-slate-600'}`}>{label}</span>;
}

/** Formats persisted UTC task timestamps for the Chinese product timeline. */
function formatTaskTime(value: string | null): string {
    const timestamp = parseAgentRunTimestamp(value);
    return timestamp ? timestamp.toLocaleString('zh-CN', { dateStyle: 'medium', timeStyle: 'short', timeZone: RUN_CENTER_TIME_ZONE }) : '时间未记录';
}

/** Formats a server-provided China Standard Time day bucket without letting the browser shift it. */
function formatTrendDay(value: string): string {
    const [year, month, day] = value.split('-');
    return year && month && day ? `${Number(month)}/${Number(day)}` : value;
}

/** Renders a compact metric label/value pair. */
function Metric({ label, value }: { label: string; value: string | number }) { return <div className="rounded-xl bg-slate-50 p-3"><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 font-semibold text-slate-900">{value}</dd></div>; }

/** Renders loading and no-data states with an optional refresh action. */
function EmptyState({ text, onRefresh }: { text: string; onRefresh?: () => void }) { return <div className="rounded-2xl border border-dashed p-10 text-center text-sm text-slate-500"><p>{text}</p>{onRefresh && <Button className="mt-4" variant="outline" onClick={onRefresh}><RefreshCw className="mr-2 h-4 w-4" />刷新</Button>}</div>; }

const tooltipStyle = { borderRadius: 12, borderColor: '#e2e8f0', boxShadow: '0 12px 30px rgba(15, 23, 42, 0.12)', fontSize: 12 };
