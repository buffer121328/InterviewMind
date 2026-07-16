'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { CheckCircle2, Circle, Loader2, RefreshCw, RotateCcw, Square, XCircle } from 'lucide-react';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { cancelAgentRun, listAgentRuns, retryAgentRun, streamAgentRunEvents, type AgentRun } from '@/lib/api/agentRuns';
import { applyAgentRunEventList, isTerminalAgentRunEvent } from '@/lib/agentRunEvents';
import { toast } from 'sonner';

interface TaskCenterDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
}

const STATUS_TEXT: Record<string, string> = {
    queued: '等待中',
    retrying: '等待重试',
    running: '执行中',
    cancel_requested: '取消中',
    succeeded: '已完成',
    failed: '失败',
    cancelled: '已取消',
};

export function TaskCenterDialog({ open, onOpenChange }: TaskCenterDialogProps) {
    const [runs, setRuns] = useState<AgentRun[]>([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(false);
    const [actingId, setActingId] = useState<string | null>(null);
    const visibleCount = useRef(20);
    const eventControllers = useRef(new Map<string, AbortController>());
    const eventSequences = useRef(new Map<string, number>());

    const load = useCallback(async (offset = 0, append = false) => {
        setLoading(true);
        try {
            const response = await listAgentRuns({ limit: append ? 20 : visibleCount.current, offset });
            setRuns(current => {
                const next = append
                    ? [...current, ...response.runs.filter(run => !current.some(existing => existing.run_id === run.run_id))]
                    : response.runs;
                visibleCount.current = Math.max(20, next.length);
                return next;
            });
            setTotal(response.total);
        } catch (error) {
            toast.error(error instanceof Error ? error.message : '加载任务失败');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        if (!open) return;
        visibleCount.current = 20;
        const initialLoad = window.setTimeout(() => void load(0, false), 0);
        const timer = window.setInterval(() => {
            void load(0, false);
        }, 10000);
        return () => {
            window.clearTimeout(initialLoad);
            window.clearInterval(timer);
        };
    }, [open, load]);

    useEffect(() => {
        const activeIds = new Set(
            open
                ? runs.filter(run => ['queued', 'retrying', 'running', 'cancel_requested'].includes(run.status)).map(run => run.run_id)
                : [],
        );
        for (const [runId, controller] of eventControllers.current) {
            if (!activeIds.has(runId)) {
                controller.abort();
                eventControllers.current.delete(runId);
            }
        }
        for (const runId of activeIds) {
            if (eventControllers.current.has(runId)) continue;
            const controller = new AbortController();
            eventControllers.current.set(runId, controller);
            void streamAgentRunEvents(
                runId,
                event => {
                    eventSequences.current.set(runId, event.sequence);
                    setRuns(current => applyAgentRunEventList(current, event));
                    if (isTerminalAgentRunEvent(event)) {
                        void load(0, false);
                    }
                },
                controller.signal,
                eventSequences.current.get(runId) || 0,
            ).catch(error => {
                if (!(error instanceof DOMException && error.name === 'AbortError')) {
                    eventControllers.current.delete(runId);
                }
            });
        }
    }, [open, runs, load]);

    useEffect(() => () => {
        for (const controller of eventControllers.current.values()) controller.abort();
        eventControllers.current.clear();
    }, []);

    const retry = async (runId: string) => {
        setActingId(runId);
        try {
            await retryAgentRun(runId);
            await load(0, false);
        } catch (error) {
            toast.error(error instanceof Error ? error.message : '重试任务失败');
        } finally {
            setActingId(null);
        }
    };

    const cancel = async (runId: string) => {
        setActingId(runId);
        try {
            await cancelAgentRun(runId);
            await load(0, false);
        } catch (error) {
            toast.error(error instanceof Error ? error.message : '取消任务失败');
        } finally {
            setActingId(null);
        }
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="flex h-[82vh] max-w-3xl flex-col overflow-hidden p-0">
                <DialogHeader className="border-b px-6 py-5 pr-12">
                    <div className="flex items-center justify-between gap-4">
                        <div>
                            <DialogTitle>后台任务中心</DialogTitle>
                            <DialogDescription>查看可恢复任务、执行进度、失败原因并重试。</DialogDescription>
                        </div>
                        <Button variant="outline" size="sm" onClick={() => void load(0, false)} disabled={loading}>
                            <RefreshCw className={loading ? 'animate-spin' : ''} />刷新
                        </Button>
                    </div>
                </DialogHeader>
                <ScrollArea className="min-h-0 flex-1">
                    <div className="space-y-3 p-6">
                        {runs.map(run => (
                            <div key={run.run_id} className="rounded-xl border border-gray-200 bg-white p-4">
                                <div className="flex items-start justify-between gap-4">
                                    <div>
                                        <div className="font-medium text-gray-900">{run.title}</div>
                                        <div className="mt-1 text-xs text-gray-400">
                                            {new Date(run.created_at).toLocaleString('zh-CN')} · {run.agent_name}@{run.agent_version} · 尝试 {run.attempts} 次
                                        </div>
                                    </div>
                                    <span className="rounded-full bg-gray-100 px-2.5 py-1 text-xs text-gray-600">
                                        {STATUS_TEXT[run.status] || run.status}
                                    </span>
                                </div>
                                <div className="mt-4 grid gap-2 sm:grid-cols-2">
                                    {run.plan.map(step => (
                                        <div key={step.id} className="flex items-center gap-2 text-sm text-gray-600">
                                            {step.status === 'completed' && <CheckCircle2 className="h-4 w-4 text-emerald-500" />}
                                            {step.status === 'running' && <Loader2 className="h-4 w-4 animate-spin text-orange-500" />}
                                            {step.status === 'failed' && <XCircle className="h-4 w-4 text-red-500" />}
                                            {step.status === 'pending' && <Circle className="h-4 w-4 text-gray-300" />}
                                            <span>{step.title}</span>
                                        </div>
                                    ))}
                                </div>
                                {run.error_message && (
                                    <div className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-700">{run.error_message}</div>
                                )}
                                <div className="mt-3 text-xs text-gray-400">
                                    尝试次数：{run.attempts}/{run.max_attempts}
                                </div>
                                <div className="mt-3 flex justify-end gap-2">
                                    {run.can_cancel && run.status !== 'cancel_requested' && (
                                        <Button variant="outline" size="sm" onClick={() => void cancel(run.run_id)} disabled={actingId === run.run_id}>
                                            <Square />取消
                                        </Button>
                                    )}
                                    {run.can_retry && (
                                        <Button variant="outline" size="sm" onClick={() => void retry(run.run_id)} disabled={actingId === run.run_id}>
                                            <RotateCcw />重试
                                        </Button>
                                    )}
                                </div>
                            </div>
                        ))}
                        {!loading && runs.length === 0 && (
                            <div className="py-16 text-center text-sm text-gray-400">暂无后台任务</div>
                        )}
                        {runs.length < total && (
                            <Button variant="outline" className="w-full" onClick={() => void load(runs.length, true)} disabled={loading}>
                                {loading && <Loader2 className="animate-spin" />}加载更多
                            </Button>
                        )}
                    </div>
                </ScrollArea>
            </DialogContent>
        </Dialog>
    );
}
