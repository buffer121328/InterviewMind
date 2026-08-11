'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { ExternalLink, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { getAgentPerformanceOverview, getAgentRunTraceLink, listModelMetricEvents } from '@/lib/api/agentRuns';
import type { AgentPerformanceOverview, ModelMetricEvent } from '@/lib/api/agentRunTypes';
import { describeModelMetricEvent, performanceCards } from '@/lib/agentPerformance';
import { toast } from 'sonner';

interface PerformanceViewProps {
    /** Selects the backend performance window; the value is bounded again server-side. */
    days: number;
}

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

/** Renders P50/P95, call amplification, token/cache, timeout and context-integrity aggregates. */
export function PerformanceOverviewTab({ days }: PerformanceViewProps) {
    const [value, setValue] = useState<AgentPerformanceOverview | null>(null);
    const [loading, setLoading] = useState(true);
    const load = useCallback(async () => {
        setLoading(true);
        try { setValue(await getAgentPerformanceOverview({ days })); }
        catch (error) { toast.error(error instanceof Error ? error.message : '性能指标加载失败'); }
        finally { setLoading(false); }
    }, [days]);
    useEffect(() => { queueMicrotask(() => void load()); }, [load]);
    const cards = useMemo(() => value ? performanceCards(value) : [], [value]);
    if (loading && !value) return <EmptyState text="正在汇总本地模型指标…" />;
    if (!value || value.sample_event_count === 0) return <EmptyState text="当前窗口暂无本地模型指标；历史运行不会被填充为虚构数据。" onRefresh={load} />;
    return <div className="space-y-5">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{cards.map(([label, content]) => <div key={label} className="rounded-2xl border bg-white p-4"><div className="text-xs text-slate-500">{label}</div><div className="mt-2 text-2xl font-semibold text-slate-900">{content}</div></div>)}</div>
        <div className="grid gap-4 lg:grid-cols-2">
            <section className="rounded-2xl border bg-white p-5"><h3 className="font-semibold">调用与 Token</h3><dl className="mt-4 grid grid-cols-2 gap-3 text-sm"><Metric label="逻辑调用" value={value.logical_call_count} /><Metric label="物理请求" value={value.physical_request_count} /><Metric label="输入 Token" value={value.input_tokens} /><Metric label="输出 Token" value={value.output_tokens} /><Metric label="缓存读取 Token" value={value.cache_read_tokens} /><Metric label="Retry 率" value={value.retry_rate == null ? '暂无样本' : `${(value.retry_rate * 100).toFixed(1)}%`} /></dl></section>
            <section className="rounded-2xl border bg-white p-5"><h3 className="font-semibold">上下文完整性</h3><p className="mt-2 text-sm text-slate-500">权威样本 {value.authoritative_context_sample_count}；无样本时不显示“零风险”。</p><div className="mt-4 space-y-2">{Object.entries(value.overflow_strategy_counts).map(([name, count]) => <div key={name} className="flex justify-between rounded-lg bg-slate-50 px-3 py-2 text-sm"><span>{name}</span><strong>{count}</strong></div>)}</div></section>
        </div>
        <div className="text-xs text-slate-500">口径：逻辑调用 = 首个主候选的 attempt 1；物理请求 = 每一次 Provider started 请求。样本事件 {value.sample_event_count}。</div>
    </div>;
}

/** Renders safe per-request model metadata and server-validated Trace actions. */
export function ModelCallsTab({ days }: PerformanceViewProps) {
    return <MetricEventList days={days} degradationsOnly={false} empty="当前窗口暂无模型调用事件。" />;
}

/** Renders failed, skipped, fallback, timeout and context-overflow events. */
export function DegradationsTab({ days }: PerformanceViewProps) {
    return <MetricEventList days={days} degradationsOnly empty="当前窗口没有记录到异常或降级事件。" />;
}

/** Loads and renders one bounded event list without exposing model input/output text. */
function MetricEventList({ days, degradationsOnly, empty }: PerformanceViewProps & { degradationsOnly: boolean; empty: string }) {
    const [events, setEvents] = useState<ModelMetricEvent[]>([]);
    const [loading, setLoading] = useState(true);
    const load = useCallback(async () => {
        setLoading(true);
        try { setEvents((await listModelMetricEvents({ days, degradationsOnly, limit: 200 })).events); }
        catch (error) { toast.error(error instanceof Error ? error.message : '模型事件加载失败'); }
        finally { setLoading(false); }
    }, [days, degradationsOnly]);
    useEffect(() => { queueMicrotask(() => void load()); }, [load]);
    if (loading && events.length === 0) return <EmptyState text="正在加载安全模型指标…" />;
    if (events.length === 0) return <EmptyState text={empty} onRefresh={load} />;
    return <div className="space-y-3">{events.map(event => <article key={event.event_id} className="rounded-2xl border bg-white p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><div className="font-medium text-slate-900">{event.event_type} · {event.stage || '未标记阶段'}</div><p className="mt-1 text-sm text-slate-500">{describeModelMetricEvent(event)}</p><p className="mt-2 text-xs text-slate-400">Run {event.run_id} · {new Date(event.timestamp).toLocaleString('zh-CN')}</p></div><Button variant="outline" size="sm" onClick={() => void openTrace(event.run_id)}><ExternalLink className="mr-1 h-3.5 w-3.5" />Trace</Button></div>{event.is_degradation && <div className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">timeout scope: {String(event.payload.timeout_scope || '未分类')} · overflow: {String(event.payload.overflow_strategy || '无')}</div>}</article>)}</div>;
}

/** Renders a compact metric label/value pair. */
function Metric({ label, value }: { label: string; value: string | number }) { return <div className="rounded-lg bg-slate-50 p-3"><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 font-semibold">{value}</dd></div>; }

/** Renders loading and no-data states with an optional refresh action. */
function EmptyState({ text, onRefresh }: { text: string; onRefresh?: () => void }) { return <div className="rounded-2xl border border-dashed p-10 text-center text-sm text-slate-500"><p>{text}</p>{onRefresh && <Button className="mt-4" variant="outline" onClick={onRefresh}><RefreshCw className="mr-2 h-4 w-4" />刷新</Button>}</div>; }
