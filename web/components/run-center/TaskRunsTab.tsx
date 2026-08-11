'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
    Activity,
    CheckCircle2,
    ChevronDown,
    ChevronUp,
    Circle,
    Clock3,
    ExternalLink,
    Eye,
    Loader2,
    RefreshCw,
    RotateCcw,
    ShieldCheck,
    Square,
    Wrench,
    XCircle,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
    cancelAgentRun,
    getAgentRunTraceLink,
    getAgentRunSummary,
    listAgentRunEvents,
    listGroupedAgentRuns,
    retryAgentRun,
    streamAgentRunEvents,
    type AgentRun,
    type AgentRunEvent,
    type GroupedAgentRun,
    type AgentRunStatus,
} from '@/lib/api/agentRuns';
import { isTerminalAgentRunEvent } from '@/lib/agentRunEvents';
import { applyAgentRunEventGroups } from '@/lib/agentRunGroups';
import {
    AGENT_RUN_CATEGORIES,
    getAgentRunCategory,
    getAgentRunCategoryLabel,
    getAgentRunGroupStatusLabel,
    getAgentRunStatusLabel,
    getInterviewSessionProgressLabel,
    groupAgentRunsForDisplay,
    latestAgentRunStatus,
    summarizeResumeRunResult,
    type AgentRunCategory,
} from '@/lib/agentRunDisplayGroups';
import { getGeneratedResume } from '@/lib/api/resume';
import { ResumePreviewDialog } from '@/components/ResumePreviewDialog';
import { PaginationControls } from '@/components/PaginationControls';
import { DEFAULT_PAGE_SIZE } from '@/lib/pagination';
import { toast } from 'sonner';
import { getAgentRunDestination, getAgentRunDestinationLabel, type AgentRunDestination } from '@/lib/agentRunDestination';
import { agentRunStatusClass as statusClass, formatAgentRunDate as formatDate, formatAgentRunDuration as duration, formatAgentRunFirstTokenDuration as firstTokenDuration, presentAgentRunEvent as eventPresentation } from '@/lib/agentRunPresentation';

const ACTIVE_STATUSES = new Set<AgentRunStatus>(['queued', 'retrying', 'running', 'cancel_requested']);

export interface TaskRunsTabProps {
    /** Returns to the unified resume workspace without bypassing any review or generation gate. */
    onOpenResumeWorkspace?: (generationSessionId?: string) => void;
    /** Opens an ownership-scoped linked interview session when the run exposes one. */
    onOpenSession?: (sessionId: string) => void;
    /** Opens the unified Markdown report for a linked interview session. */
    onOpenReport?: (sessionId: string) => void;
    /** Opens an owner-scoped captured job detail. */
    onOpenJob?: (jobId: number) => void;
    /** Opens the persisted ability growth record. */
    onOpenGrowthRecord?: () => void;
}

/** Renders the owner-scoped AgentRun lifecycle view and approved business-result actions. */
export function TaskRunsTab({ onOpenResumeWorkspace, onOpenSession, onOpenReport, onOpenJob, onOpenGrowthRecord }: TaskRunsTabProps) {
    const [groups, setGroups] = useState<GroupedAgentRun[]>([]);
    const [summary, setSummary] = useState({ active: 0, history: 0, succeeded: 0, failed: 0 });
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [actingId, setActingId] = useState<string | null>(null);
    const [statusFilter, setStatusFilter] = useState<'all' | 'active' | AgentRunStatus>('all');
    const [taskFilter, setTaskFilter] = useState<'all' | AgentRunCategory>('all');
    const [page, setPage] = useState(1);
    const [expandedRunId, setExpandedRunId] = useState<string | null>(null);
    const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({});
    const [eventsByRun, setEventsByRun] = useState<Record<string, AgentRunEvent[]>>({});
    const [eventsLoadingId, setEventsLoadingId] = useState<string | null>(null);
    const [previewResume, setPreviewResume] = useState<{ id: number; title: string; content: string } | null>(null);
    const [previewLoadingId, setPreviewLoadingId] = useState<number | null>(null);
    const controllers = useRef(new Map<string, AbortController>());
    const eventSequences = useRef(new Map<string, number>());

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const [response, runSummary] = await Promise.all([listGroupedAgentRuns({
                status: statusFilter !== 'all' && statusFilter !== 'active' ? statusFilter : undefined,
                limit: 200,
            }), getAgentRunSummary()]);
            setGroups(response.groups
                .map(group => ({
                    ...group,
                    runs: group.runs.filter(run => (statusFilter !== 'active' || ACTIVE_STATUSES.has(run.status))
                        && (taskFilter === 'all' || getAgentRunCategory(run.task_type) === taskFilter)),
                }))
                .filter(group => group.runs.length > 0));
            setSummary(runSummary);
            setError(null);
        } catch (loadError) {
            const message = loadError instanceof Error ? loadError.message : '';
            setError(/failed to fetch/i.test(message) ? '无法连接后端，请确认 FastAPI 与 Worker 已启动。' : message || '读取任务运行失败');
        } finally {
            setLoading(false);
        }
    }, [statusFilter, taskFilter]);

    useEffect(() => {
        const initialLoad = window.setTimeout(() => void load(), 0);
        const timer = window.setInterval(() => void load(), 15_000);
        return () => {
            window.clearTimeout(initialLoad);
            window.clearInterval(timer);
        };
    }, [load]);

    useEffect(() => {
        const activeIds = new Set<string>();
        for (const group of groups) {
            for (const run of group.runs) {
                if (ACTIVE_STATUSES.has(run.status)) activeIds.add(run.run_id);
            }
        }
        for (const [runId, controller] of controllers.current) {
            if (!activeIds.has(runId)) {
                controller.abort();
                controllers.current.delete(runId);
            }
        }
        for (const runId of activeIds) {
            if (controllers.current.has(runId)) continue;
            const controller = new AbortController();
            controllers.current.set(runId, controller);
            void streamAgentRunEvents(
                runId,
                event => {
                    eventSequences.current.set(runId, event.sequence);
                    setGroups(current => applyAgentRunEventGroups(current, event));
                    setEventsByRun(current => {
                        const existing = current[runId];
                        if (!existing || existing.some(item => item.event_id === event.event_id)) return current;
                        return {
                            ...current,
                            [runId]: [...existing, event].sort((a, b) => a.sequence - b.sequence),
                        };
                    });
                    if (isTerminalAgentRunEvent(event)) void load();
                },
                controller.signal,
                eventSequences.current.get(runId) || 0,
            ).catch(error => {
                if (!(error instanceof DOMException && error.name === 'AbortError')) {
                    controllers.current.delete(runId);
                }
            });
        }
    }, [groups, load]);

    useEffect(() => () => {
        for (const controller of controllers.current.values()) controller.abort();
        controllers.current.clear();
    }, []);

    // The API owns persistence and SSE updates; the browser only maps internal run types to stable product categories.
    const allDisplayGroups = useMemo(() => groupAgentRunsForDisplay(groups), [groups]);
    const displayGroups = useMemo(
        () => allDisplayGroups.slice((page - 1) * DEFAULT_PAGE_SIZE, page * DEFAULT_PAGE_SIZE),
        [allDisplayGroups, page],
    );
    const categoryTotals = useMemo(() => allDisplayGroups.reduce((counts, group) => {
        counts[group.category] += group.runs.length;
        return counts;
    }, { 'text-interview': 0, 'voice-interview': 0, 'resume-optimization': 0, 'job-delivery': 0 } as Record<AgentRunCategory, number>), [allDisplayGroups]);

    /** Toggles one local business-and-date section; child run detail disclosure remains independent. */
    const toggleGroup = (groupKey: string) => {
        setExpandedGroups(current => ({ ...current, [groupKey]: !(current[groupKey] ?? false) }));
    };

    /** Handles retry; updates local UI state first and delegates server mutations through the approved API boundary. */
    const handleRetry = async (run: AgentRun) => {
        setActingId(run.run_id);
        try {
            await retryAgentRun(run.run_id);
            toast.success('重试请求已提交');
            await load();
        } catch (error) {
            toast.error(error instanceof Error ? error.message : '重试失败');
        } finally {
            setActingId(null);
        }
    };

    /** Handles cancel; updates local UI state first and delegates server mutations through the approved API boundary. */
    const handleCancel = async (run: AgentRun) => {
        if (!window.confirm(`确认取消任务「${run.title}」？`)) return;
        setActingId(run.run_id);
        try {
            await cancelAgentRun(run.run_id);
            toast.success('取消请求已提交');
            await load();
        } catch (error) {
            toast.error(error instanceof Error ? error.message : '取消失败');
        } finally {
            setActingId(null);
        }
    };

    /** Encapsulates toggle details; returns typed data or state and keeps side effects within the owning module boundary. */
    const toggleDetails = async (run: AgentRun) => {
        if (expandedRunId === run.run_id) {
            setExpandedRunId(null);
            return;
        }
        setExpandedRunId(run.run_id);
        if (eventsByRun[run.run_id]) return;
        setEventsLoadingId(run.run_id);
        try {
            const events = await listAgentRunEvents(run.run_id);
            setEventsByRun(current => ({ ...current, [run.run_id]: events }));
        } catch (eventError) {
            toast.error(eventError instanceof Error ? eventError.message : '读取运行详情失败');
        } finally {
            setEventsLoadingId(null);
        }
    };

    /** Opens the one deterministic business destination associated with a run. */
    async function handleOpenDestination(destination: AgentRunDestination) {
        if (destination.kind === 'generated-resume') return handleOpenGeneratedResume(destination.resumeId);
        if (destination.kind === 'interview-report') return onOpenReport?.(destination.sessionId);
        if (destination.kind === 'interview-session') return onOpenSession?.(destination.sessionId);
        if (destination.kind === 'resume-workspace') return onOpenResumeWorkspace?.(destination.generationSessionId);
        if (destination.kind === 'job') return onOpenJob?.(destination.jobId);
        onOpenGrowthRecord?.();
    }

    /** Handles open trace; updates local UI state first and delegates server mutations through the approved API boundary. */
    const handleOpenTrace = async (run: AgentRun) => {
        setActingId(run.run_id);
        try {
            const trace = await getAgentRunTraceLink(run.run_id);
            if (!trace.available || !trace.url) {
                toast.info(trace.message || '当前 Trace 暂不可访问');
                return;
            }
            const opened = window.open(trace.url, '_blank', 'noopener,noreferrer');
            if (!opened) toast.warning('浏览器拦截了新窗口，请允许后重试');
        } catch (traceError) {
            toast.error(traceError instanceof Error ? traceError.message : '打开 Langfuse 失败');
        } finally {
            setActingId(null);
        }
    };

    /** Loads only the persisted generated resume selected by its public artifact id, then opens the shared preview/export dialog. */
    const handleOpenGeneratedResume = async (resumeId: number) => {
        setPreviewLoadingId(resumeId);
        try {
            const resume = await getGeneratedResume(resumeId);
            if (!resume?.content) {
                toast.error('未找到生成的简历内容，可能已被删除');
                return;
            }
            setPreviewResume({ id: resume.id, title: resume.title, content: resume.content });
        } catch (resumeError) {
            toast.error(resumeError instanceof Error ? resumeError.message : '读取生成简历失败');
        } finally {
            setPreviewLoadingId(null);
        }
    };

    return (
        <div className="mx-auto w-full max-w-7xl p-5 sm:p-6">
            <section className="grid gap-3 sm:grid-cols-4">
                {[
                    ['活跃任务', summary.active, 'text-teal-700'],
                    ['历史总任务', summary.history, 'text-slate-950'],
                    ['已完成任务', summary.succeeded, 'text-emerald-700'],
                    ['失败', summary.failed, 'text-red-700'],
                ].map(([label, value, color]) => (
                    <div key={String(label)} className="surface-panel p-4">
                        <div className="text-xs text-slate-500">{label}</div>
                        <div className={`mt-2 text-2xl font-semibold ${color}`}>{value}</div>
                    </div>
                ))}
            </section>

            <section className="surface-panel mt-5 flex flex-col justify-between gap-4 p-4 sm:flex-row sm:items-center">
                <div>
                    <div className="flex items-center gap-2 text-sm font-semibold text-slate-950"><Activity className="h-4 w-4 text-teal-700" />可恢复 Agent 任务</div>
                    <p className="mt-1 text-xs text-slate-500">列表通过 SSE 接收实时事件，低频刷新用于断线兜底。当前筛选：文本面试 {categoryTotals['text-interview']} 项、语音面试 {categoryTotals['voice-interview']} 项、简历优化 {categoryTotals['resume-optimization']} 项、岗位投递 {categoryTotals['job-delivery']} 项。</p>
                    <p className="mt-1 text-xs font-medium text-teal-700">任务状态表示单次 Agent 执行；整场面试是否结束以面试会话进度为准。</p>
                    <p className="mt-1 text-xs text-slate-500">仅整理可确认加密会话引用归属当前用户的历史面试任务，不会暴露任务载荷。</p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <select aria-label="状态筛选" value={statusFilter} onChange={event => { setStatusFilter(event.target.value as typeof statusFilter); setPage(1); }} className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-xs">
                        <option value="all">全部状态</option>
                        <option value="active">活跃任务</option>
                        <option value="succeeded">任务已完成</option>
                        <option value="failed">失败</option>
                        <option value="cancelled">已取消</option>
                    </select>
                    <select aria-label="任务类型筛选" value={taskFilter} onChange={event => { setTaskFilter(event.target.value as typeof taskFilter); setPage(1); }} className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-xs">
                        <option value="all">全部类型</option>
                        {AGENT_RUN_CATEGORIES.map(({ value, label }) => <option key={value} value={value}>{label}</option>)}
                    </select>
                    <Button variant="outline" size="sm" onClick={() => void load()} disabled={loading}><RefreshCw className={loading ? 'animate-spin' : ''} />刷新</Button>
                </div>
            </section>

            {error && (
                <div role="alert" className="mt-4 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">{error}</div>
            )}

            <section className="mt-4 space-y-3">
                {loading && groups.length === 0 ? (
                    <div role="status" aria-live="polite" className="surface-panel flex min-h-64 items-center justify-center text-sm text-slate-500"><Loader2 className="mr-2 h-4 w-4 animate-spin text-teal-700" aria-hidden="true" />读取运行记录...</div>
                ) : displayGroups.length === 0 ? (
                    <div className="surface-panel flex min-h-64 flex-col items-center justify-center text-center">
                        <Activity className="h-9 w-9 text-slate-300" />
                        <div className="mt-3 text-sm font-medium text-slate-900">当前筛选下没有任务</div>
                        <p className="mt-1 text-xs text-slate-500">启动面试、简历优化、报告或投递资产任务后会显示在这里。</p>
                    </div>
                ) : displayGroups.map(group => {
                    const groupKey = group.key;
                    const groupId = `agent-run-group-${groupKey.replace(/[^a-zA-Z0-9_-]/g, '-')}`;
                    const activeCount = group.runs.filter(run => ACTIVE_STATUSES.has(run.status)).length;
                    // New groups are compact unless work is active; explicit user choices survive polling.
                    const isGroupExpanded = expandedGroups[groupKey] ?? activeCount > 0;
                    const aggregateStatus = latestAgentRunStatus(group.runs);
                    const latestRun = group.runs[0];
                    return (
                    <div key={groupKey} className="overflow-hidden rounded-2xl border border-slate-200/80 bg-white/70 shadow-sm shadow-slate-200/40">
                        <button
                            type="button"
                            className="flex w-full items-center justify-between gap-4 px-4 py-4 text-left transition-colors hover:bg-teal-50/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-teal-600 sm:px-5"
                            aria-expanded={isGroupExpanded}
                            aria-controls={groupId}
                            onClick={() => toggleGroup(groupKey)}
                        >
                            <span className="flex min-w-0 items-center gap-3">
                                <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${group.category === 'resume-optimization' ? 'bg-violet-100 text-violet-700' : group.category === 'job-delivery' ? 'bg-amber-100 text-amber-700' : 'bg-teal-100 text-teal-700'}`}>
                                    <Activity className="h-4 w-4" aria-hidden="true" />
                                </span>
                                <span className="min-w-0">
                                    <span className="flex flex-wrap items-center gap-2">
                                        <span className="text-sm font-semibold text-slate-950">{group.categoryLabel}</span>
                                        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-600">{group.dateLabel}</span>
                                        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-600">{group.runs.length} 项</span>
                                        {aggregateStatus && <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${statusClass(aggregateStatus)}`}>{getAgentRunGroupStatusLabel(group.category, aggregateStatus)}</span>}
                                        {activeCount > 0 && <span className="rounded-full bg-teal-50 px-2 py-0.5 text-[10px] font-medium text-teal-700">{activeCount} 活跃</span>}
                                    </span>
                                    <span className="mt-1 block truncate text-[10px] text-slate-400">
                                        按创建时间排列{latestRun ? ` · 最近创建 ${formatDate(latestRun.created_at)}` : ''}
                                    </span>
                                </span>
                            </span>
                            <span className="flex shrink-0 items-center gap-2 text-xs text-slate-400">
                                <span className="hidden sm:inline">{isGroupExpanded ? '收起' : '展开'}</span>
                                {isGroupExpanded ? <ChevronUp className="h-4 w-4" aria-hidden="true" /> : <ChevronDown className="h-4 w-4" aria-hidden="true" />}
                            </span>
                        </button>
                        {isGroupExpanded && <div id={groupId} className="max-h-[70vh] space-y-3 overflow-y-auto overscroll-contain border-t border-slate-100 bg-slate-50/35 p-3 pr-2 sm:p-4 sm:pr-3">
                        {group.runs.map(run => (
                    <article key={run.run_id} className="surface-panel p-5 transition-shadow hover:shadow-md hover:shadow-slate-200/50">
                        <div className="flex flex-col justify-between gap-4 md:flex-row md:items-start">
                            <div className="min-w-0">
                                <div className="flex flex-wrap items-center gap-2">
                                    <h3 className="text-sm font-semibold text-slate-950">{run.title || getAgentRunCategoryLabel(getAgentRunCategory(run.task_type))}</h3>
                                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${statusClass(run.status)}`}>{getAgentRunStatusLabel(run)}</span>
                                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-600">{getAgentRunCategoryLabel(getAgentRunCategory(run.task_type))}</span>
                                </div>
                                {getInterviewSessionProgressLabel(run) && (
                                    <div className="mt-2 inline-flex rounded-lg border border-teal-100 bg-teal-50 px-2.5 py-1 text-[11px] font-medium text-teal-800">
                                        {getInterviewSessionProgressLabel(run)}
                                    </div>
                                )}
                                <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-slate-400">
                                    <span>{run.agent_name}@{run.agent_version}</span>
                                    <span className="max-w-full break-all font-mono" title={`运行 ID：${run.run_id}`} aria-label={`运行 ID：${run.run_id}`}>{run.run_id}</span>
                                    <span className="inline-flex items-center gap-1"><Clock3 className="h-3 w-3" />更新 {formatDate(run.updated_at)} · 总耗时 {duration(run)} · 首 Token {firstTokenDuration(run.first_token_duration_ms)}</span>
                                    <span>尝试 {run.attempts}/{run.max_attempts}</span>
                                </div>
                            </div>
                            <div className="flex flex-wrap gap-2">
                                {(() => {
                                    const destination = getAgentRunDestination(run);
                                    if (!destination) return null;
                                    const supported = destination.kind === 'generated-resume'
                                        || (destination.kind === 'interview-session' && onOpenSession)
                                        || (destination.kind === 'interview-report' && onOpenReport)
                                        || (destination.kind === 'resume-workspace' && onOpenResumeWorkspace)
                                        || (destination.kind === 'job' && onOpenJob)
                                        || (destination.kind === 'growth-record' && onOpenGrowthRecord);
                                    if (!supported) return null;
                                    const loadingDestination = destination.kind === 'generated-resume' && previewLoadingId === destination.resumeId;
                                    return (
                                        <Button variant="outline" size="sm" onClick={() => void handleOpenDestination(destination)} disabled={loadingDestination}>
                                            {loadingDestination ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ExternalLink className="h-3.5 w-3.5" />}
                                            {getAgentRunDestinationLabel(destination)}
                                        </Button>
                                    );
                                })()}
                                {run.trace_id && (
                                    <Button variant="outline" size="sm" onClick={() => void handleOpenTrace(run)} disabled={actingId === run.run_id}>
                                        <ExternalLink className="h-3.5 w-3.5" />Langfuse
                                    </Button>
                                )}
                                {!run.trace_id && (
                                    <span
                                        className="inline-flex h-9 items-center rounded-md border border-dashed border-slate-200 px-3 text-xs text-slate-400"
                                        title="该历史任务没有生成可访问的 Langfuse Trace；新任务仅在 Langfuse 正常启用时显示链接"
                                    >
                                        Langfuse 未记录
                                    </span>
                                )}
                                <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => void toggleDetails(run)}
                                    aria-expanded={expandedRunId === run.run_id}
                                    aria-controls={`agent-run-details-${run.run_id}`}
                                >
                                    {expandedRunId === run.run_id
                                        ? <ChevronUp className="h-3.5 w-3.5" />
                                        : <ChevronDown className="h-3.5 w-3.5" />}
                                    运行详情
                                </Button>
                                {run.can_cancel && run.status !== 'cancel_requested' && (
                                    <Button variant="outline" size="sm" onClick={() => void handleCancel(run)} disabled={actingId === run.run_id}>
                                        <Square className="h-3.5 w-3.5" />取消
                                    </Button>
                                )}
                                {run.can_retry && (
                                    <Button variant="outline" size="sm" onClick={() => void handleRetry(run)} disabled={actingId === run.run_id}>
                                        <RotateCcw className="h-3.5 w-3.5" />重试
                                    </Button>
                                )}
                            </div>
                        </div>

                        <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                            {run.plan.map(step => (
                                <div key={step.id} className={`flex items-center gap-2 rounded-xl border px-3 py-2.5 text-xs ${step.status === 'running' ? 'border-teal-200 bg-teal-50 text-teal-800' : 'border-slate-200 bg-slate-50 text-slate-600'}`}>
                                    {step.status === 'completed' && <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-500" />}
                                    {step.status === 'running' && <Loader2 className="h-4 w-4 shrink-0 animate-spin text-teal-600" />}
                                    {step.status === 'failed' && <XCircle className="h-4 w-4 shrink-0 text-red-500" />}
                                    {step.status === 'pending' && <Circle className="h-4 w-4 shrink-0 text-slate-300" />}
                                    <span className="truncate">{step.title}</span>
                                </div>
                            ))}
                        </div>

                        {run.error_message && (
                            <div role="alert" className="mt-4 rounded-xl border border-red-200 bg-red-50 p-3 text-xs leading-5 text-red-800">{run.error_message}</div>
                        )}

                        {expandedRunId === run.run_id && (
                            <div id={`agent-run-details-${run.run_id}`} className="mt-4 border-t border-slate-100 pt-4">
                                {(() => {
                                    const resumeResult = (run.task_type === 'resume_optimize' || run.task_type === 'resume_workspace' || run.task_type === 'resume_generation')
                                        ? summarizeResumeRunResult(run.result, run.task_type)
                                        : null;
                                    return resumeResult && (
                                        <section className="mb-4 rounded-xl border border-violet-100 bg-violet-50/50 p-3" aria-label="简历任务结果摘要">
                                            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                                                <div className="text-xs font-semibold text-violet-900">简历任务结果</div>
                                                {resumeResult.resultId && <span className="font-mono text-[10px] text-violet-700">结果 ID：{resumeResult.resultId}</span>}
                                            </div>
                                            <div className="mt-2 space-y-1.5">
                                                {resumeResult.stages.map(stage => <p key={stage.label} className="text-[11px] leading-4 text-violet-950"><span className="font-medium">{stage.label}：</span>{stage.detail}</p>)}
                                            </div>
                                            <p className="mt-2 text-[11px] text-violet-800">
                                                {resumeResult.artifact
                                                    ? <>最终生成文件：{resumeResult.artifact.name || '已生成简历'}{resumeResult.artifact.id ? `（ID：${resumeResult.artifact.id}）` : ''}</>
                                                    : '最终生成文件/成品尚未生成'}
                                            </p>
                                        </section>
                                    );
                                })()}
                                <div className="mb-3 flex items-center justify-between">
                                    <div>
                                        <div className="text-xs font-semibold text-slate-800">审计事件</div>
                                        <p className="mt-1 text-[10px] text-slate-400">展示任务生命周期、工具调用、输入输出安全检查和 Prompt 版本。</p>
                                    </div>
                                    {run.trace_id && <span className="max-w-48 truncate font-mono text-[9px] text-slate-400">Trace {run.trace_id}</span>}
                                </div>
                                {eventsLoadingId === run.run_id ? (
                                    <div className="flex items-center py-4 text-xs text-slate-500"><Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />读取审计记录...</div>
                                ) : (eventsByRun[run.run_id] || []).length === 0 ? (
                                    <div className="rounded-xl bg-slate-50 p-4 text-xs text-slate-500">该任务暂无可展示的事件。</div>
                                ) : (
                                    <div className="space-y-2">
                                        {(eventsByRun[run.run_id] || []).slice(-50).map(event => {
                                            const presentation = eventPresentation(event);
                                            return (
                                                <div key={event.event_id || `${event.sequence}-${event.type}`} className="flex gap-3 rounded-xl border border-slate-100 bg-slate-50/70 px-3 py-2.5">
                                                    <div className="mt-0.5">
                                                        {presentation.kind === 'tool' && <Wrench className="h-3.5 w-3.5 text-indigo-500" />}
                                                        {presentation.kind === 'guardrail' && <ShieldCheck className="h-3.5 w-3.5 text-emerald-600" />}
                                                        {presentation.kind === 'lifecycle' && <Activity className="h-3.5 w-3.5 text-teal-600" />}
                                                    </div>
                                                    <div className="min-w-0 flex-1">
                                                        <div className="flex flex-wrap items-center justify-between gap-2">
                                                            <span className="text-xs font-medium text-slate-800">{presentation.title}</span>
                                                            <span className="text-[9px] text-slate-400">#{event.sequence} · {formatDate(event.timestamp)}</span>
                                                        </div>
                                                        <p className="mt-1 break-words text-[10px] leading-4 text-slate-500">{presentation.detail}</p>
                                                    </div>
                                                </div>
                                            );
                                        })}
                                    </div>
                                )}
                            </div>
                        )}
                    </article>
                        ))}
                        </div>}
                    </div>
                    );
                })}
            </section>
            <PaginationControls
                className="mt-5"
                page={page}
                total={allDisplayGroups.length}
                loading={loading}
                onPageChange={setPage}
            />
            {previewResume && (
                <ResumePreviewDialog
                    isOpen={true}
                    onClose={() => setPreviewResume(null)}
                    title={previewResume.title}
                    content={previewResume.content}
                    resumeId={previewResume.id}
                />
            )}
        </div>
    );
}
