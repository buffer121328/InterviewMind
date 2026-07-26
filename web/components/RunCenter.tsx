'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
    Activity,
    CheckCircle2,
    Circle,
    Clock3,
    Loader2,
    RefreshCw,
    RotateCcw,
    Square,
    XCircle,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
    cancelAgentRun,
    listAgentRuns,
    retryAgentRun,
    streamAgentRunEvents,
    type AgentRun,
    type AgentRunStatus,
    type AgentRunTaskType,
} from '@/lib/api/agentRuns';
import { applyAgentRunEventList, isTerminalAgentRunEvent } from '@/lib/agentRunEvents';
import { toast } from 'sonner';

const STATUS_LABELS: Record<AgentRunStatus, string> = {
    queued: '排队中',
    retrying: '等待重试',
    running: '运行中',
    cancel_requested: '取消中',
    succeeded: '已完成',
    failed: '失败',
    cancelled: '已取消',
};

const TASK_LABELS: Record<AgentRunTaskType, string> = {
    interview_start: '面试启动',
    interview_turn: '面试回合',
    voice_interview_turn: '语音面试',
    resume_optimize: '简历优化',
    interview_report: '面试报告',
    job_assets: '投递资产',
};

const ACTIVE_STATUSES = new Set<AgentRunStatus>(['queued', 'retrying', 'running', 'cancel_requested']);

function formatDate(value?: string | null) {
    if (!value) return '-';
    return new Date(value).toLocaleString('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
    });
}

function duration(run: AgentRun) {
    if (!run.started_at) return '-';
    const end = run.finished_at ? new Date(run.finished_at).getTime() : Date.now();
    const ms = Math.max(0, end - new Date(run.started_at).getTime());
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
    return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1000)}s`;
}

function statusClass(status: AgentRunStatus) {
    if (status === 'succeeded') return 'bg-emerald-50 text-emerald-700';
    if (status === 'failed') return 'bg-red-50 text-red-700';
    if (status === 'cancelled') return 'bg-slate-100 text-slate-600';
    return 'bg-teal-50 text-teal-700';
}

export function RunCenter() {
    const [runs, setRuns] = useState<AgentRun[]>([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [actingId, setActingId] = useState<string | null>(null);
    const [statusFilter, setStatusFilter] = useState<'all' | 'active' | AgentRunStatus>('all');
    const [taskFilter, setTaskFilter] = useState<'all' | AgentRunTaskType>('all');
    const controllers = useRef(new Map<string, AbortController>());
    const eventSequences = useRef(new Map<string, number>());

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const response = await listAgentRuns({
                status: statusFilter !== 'all' && statusFilter !== 'active' ? statusFilter : undefined,
                taskType: taskFilter !== 'all' ? taskFilter : undefined,
                limit: 100,
            });
            setRuns(statusFilter === 'active' ? response.runs.filter(run => ACTIVE_STATUSES.has(run.status)) : response.runs);
            setTotal(response.total);
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
        const activeIds = new Set(runs.filter(run => ACTIVE_STATUSES.has(run.status)).map(run => run.run_id));
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
                    setRuns(current => applyAgentRunEventList(current, event));
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
    }, [runs, load]);

    useEffect(() => () => {
        for (const controller of controllers.current.values()) controller.abort();
        controllers.current.clear();
    }, []);

    const stats = useMemo(() => ({
        active: runs.filter(run => ACTIVE_STATUSES.has(run.status)).length,
        succeeded: runs.filter(run => run.status === 'succeeded').length,
        failed: runs.filter(run => run.status === 'failed').length,
    }), [runs]);

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

    return (
        <div className="mx-auto h-full w-full max-w-7xl overflow-y-auto p-5 sm:p-6">
            <section className="grid gap-3 sm:grid-cols-4">
                {[
                    ['当前列表', runs.length, 'text-slate-950'],
                    ['活跃任务', stats.active, 'text-teal-700'],
                    ['已完成', stats.succeeded, 'text-emerald-700'],
                    ['失败', stats.failed, 'text-red-700'],
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
                    <p className="mt-1 text-xs text-slate-500">列表通过 SSE 接收实时事件，低频刷新用于断线兜底。总记录 {total} 条。</p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <select value={statusFilter} onChange={event => setStatusFilter(event.target.value as typeof statusFilter)} className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-xs">
                        <option value="all">全部状态</option>
                        <option value="active">活跃任务</option>
                        <option value="succeeded">已完成</option>
                        <option value="failed">失败</option>
                        <option value="cancelled">已取消</option>
                    </select>
                    <select value={taskFilter} onChange={event => setTaskFilter(event.target.value as typeof taskFilter)} className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-xs">
                        <option value="all">全部类型</option>
                        {Object.entries(TASK_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                    </select>
                    <Button variant="outline" size="sm" onClick={() => void load()} disabled={loading}><RefreshCw className={loading ? 'animate-spin' : ''} />刷新</Button>
                </div>
            </section>

            {error && (
                <div className="mt-4 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">{error}</div>
            )}

            <section className="mt-4 space-y-3">
                {loading && runs.length === 0 ? (
                    <div className="surface-panel flex min-h-64 items-center justify-center text-sm text-slate-500"><Loader2 className="mr-2 h-4 w-4 animate-spin text-teal-700" />读取运行记录...</div>
                ) : runs.length === 0 ? (
                    <div className="surface-panel flex min-h-64 flex-col items-center justify-center text-center">
                        <Activity className="h-9 w-9 text-slate-300" />
                        <div className="mt-3 text-sm font-medium text-slate-900">当前筛选下没有任务</div>
                        <p className="mt-1 text-xs text-slate-500">启动面试、简历优化、报告或投递资产任务后会显示在这里。</p>
                    </div>
                ) : runs.map(run => (
                    <article key={run.run_id} className="surface-panel p-5">
                        <div className="flex flex-col justify-between gap-4 md:flex-row md:items-start">
                            <div className="min-w-0">
                                <div className="flex flex-wrap items-center gap-2">
                                    <h3 className="text-sm font-semibold text-slate-950">{run.title || TASK_LABELS[run.task_type]}</h3>
                                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${statusClass(run.status)}`}>{STATUS_LABELS[run.status]}</span>
                                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-600">{TASK_LABELS[run.task_type]}</span>
                                </div>
                                <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-slate-400">
                                    <span>{run.agent_name}@{run.agent_version}</span>
                                    <span>{run.run_id}</span>
                                    <span className="inline-flex items-center gap-1"><Clock3 className="h-3 w-3" />{formatDate(run.updated_at)} · {duration(run)}</span>
                                    <span>尝试 {run.attempts}/{run.max_attempts}</span>
                                </div>
                            </div>
                            <div className="flex gap-2">
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
                            <div className="mt-4 rounded-xl border border-red-200 bg-red-50 p-3 text-xs leading-5 text-red-800">{run.error_message}</div>
                        )}
                    </article>
                ))}
            </section>
        </div>
    );
}
