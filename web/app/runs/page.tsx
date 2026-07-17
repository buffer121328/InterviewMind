'use client';

import { useEffect, useMemo, useState } from 'react';
import { listAgentRuns, type AgentRun, type AgentRunStatus, type AgentRunTaskType } from '@/lib/api/agentRuns';

const STATUS_LABELS: Record<AgentRunStatus, string> = {
    queued: '排队中',
    retrying: '重试中',
    running: '运行中',
    cancel_requested: '取消中',
    succeeded: '成功',
    failed: '失败',
    cancelled: '已取消',
};

const TASK_LABELS: Record<AgentRunTaskType, string> = {
    interview_start: '面试启动',
    interview_turn: '面试回合',
    voice_interview_turn: '语音面试',
    resume_optimize: '简历优化',
    interview_report: '面试报告',
    job_assets: '求职素材',
};

const TERMINAL_STATUSES = new Set<AgentRunStatus>(['succeeded', 'failed', 'cancelled']);

function formatDuration(ms: number | null): string {
    if (ms === null || !Number.isFinite(ms) || ms < 0) return '-';
    if (ms < 1000) return `${Math.round(ms)}ms`;
    if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
    return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1000)}s`;
}

function runDurationMs(run: AgentRun): number | null {
    if (!run.started_at || !run.finished_at) return null;
    return new Date(run.finished_at).getTime() - new Date(run.started_at).getTime();
}

function formatDate(value: string | null | undefined): string {
    if (!value) return '-';
    return new Intl.DateTimeFormat('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
    }).format(new Date(value));
}

export default function AgentRunStatsPage() {
    const [runs, setRuns] = useState<AgentRun[]>([]);
    const [total, setTotal] = useState(0);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;
        listAgentRuns({ limit: 100 })
            .then(result => {
                if (cancelled) return;
                setRuns(result.runs);
                setTotal(result.total);
                setError(null);
            })
            .catch(err => {
                if (cancelled) return;
                setError(err instanceof Error ? err.message : '读取运行统计失败');
            })
            .finally(() => {
                if (!cancelled) setIsLoading(false);
            });
        return () => {
            cancelled = true;
        };
    }, []);

    const stats = useMemo(() => {
        const statusCounts = new Map<AgentRunStatus, number>();
        const taskCounts = new Map<AgentRunTaskType, number>();
        const durations = runs.map(runDurationMs).filter((value): value is number => value !== null);
        for (const run of runs) {
            statusCounts.set(run.status, (statusCounts.get(run.status) || 0) + 1);
            taskCounts.set(run.task_type, (taskCounts.get(run.task_type) || 0) + 1);
        }
        const avgDuration = durations.length
            ? durations.reduce((sum, value) => sum + value, 0) / durations.length
            : null;
        const activeCount = runs.filter(run => !TERMINAL_STATUSES.has(run.status)).length;
        const failedCount = runs.filter(run => run.status === 'failed').length;
        return { statusCounts, taskCounts, avgDuration, activeCount, failedCount };
    }, [runs]);

    return (
        <main className="min-h-screen bg-slate-950 px-6 py-8 text-slate-100">
            <div className="mx-auto flex max-w-6xl flex-col gap-6">
                <header className="flex flex-col gap-2">
                    <p className="text-sm uppercase tracking-[0.3em] text-indigo-300">Agent Runs</p>
                    <h1 className="text-3xl font-semibold">本地运行统计</h1>
                    <p className="text-sm text-slate-400">基于最近 100 条 AgentRun 本地聚合，不新增后端统计接口。</p>
                </header>

                {error && (
                    <div className="rounded-2xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-200">
                        {error}
                    </div>
                )}

                <section className="grid gap-4 md:grid-cols-4">
                    <StatCard label="总运行数" value={isLoading ? '...' : String(total)} />
                    <StatCard label="当前活跃" value={isLoading ? '...' : String(stats.activeCount)} />
                    <StatCard label="失败数" value={isLoading ? '...' : String(stats.failedCount)} />
                    <StatCard label="平均耗时" value={isLoading ? '...' : formatDuration(stats.avgDuration)} />
                </section>

                <section className="grid gap-4 lg:grid-cols-2">
                    <DistributionCard
                        title="状态分布"
                        entries={[...stats.statusCounts.entries()].map(([status, count]) => [STATUS_LABELS[status], count])}
                    />
                    <DistributionCard
                        title="任务类型"
                        entries={[...stats.taskCounts.entries()].map(([taskType, count]) => [TASK_LABELS[taskType], count])}
                    />
                </section>

                <section className="overflow-hidden rounded-2xl border border-white/10 bg-white/[0.03]">
                    <div className="border-b border-white/10 px-5 py-4">
                        <h2 className="font-medium">最近运行</h2>
                    </div>
                    <div className="overflow-x-auto">
                        <table className="w-full min-w-[760px] text-left text-sm">
                            <thead className="bg-white/[0.04] text-xs uppercase tracking-wide text-slate-400">
                                <tr>
                                    <th className="px-5 py-3">任务</th>
                                    <th className="px-5 py-3">状态</th>
                                    <th className="px-5 py-3">阶段</th>
                                    <th className="px-5 py-3">尝试</th>
                                    <th className="px-5 py-3">耗时</th>
                                    <th className="px-5 py-3">更新时间</th>
                                </tr>
                            </thead>
                            <tbody>
                                {isLoading ? (
                                    <tr><td className="px-5 py-6 text-slate-400" colSpan={6}>加载中...</td></tr>
                                ) : runs.length === 0 ? (
                                    <tr><td className="px-5 py-6 text-slate-400" colSpan={6}>暂无运行记录</td></tr>
                                ) : runs.map(run => (
                                    <tr key={run.run_id} className="border-t border-white/5">
                                        <td className="px-5 py-4">
                                            <div className="font-medium text-slate-100">{run.title || TASK_LABELS[run.task_type]}</div>
                                            <div className="text-xs text-slate-500">{run.run_id}</div>
                                        </td>
                                        <td className="px-5 py-4">{STATUS_LABELS[run.status]}</td>
                                        <td className="px-5 py-4 text-slate-300">{run.stage || '-'}</td>
                                        <td className="px-5 py-4 text-slate-300">{run.attempts}/{run.max_attempts}</td>
                                        <td className="px-5 py-4 text-slate-300">{formatDuration(runDurationMs(run))}</td>
                                        <td className="px-5 py-4 text-slate-300">{formatDate(run.updated_at)}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </section>
            </div>
        </main>
    );
}

function StatCard({ label, value }: { label: string; value: string }) {
    return (
        <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-5">
            <div className="text-sm text-slate-400">{label}</div>
            <div className="mt-2 text-2xl font-semibold">{value}</div>
        </div>
    );
}

function DistributionCard({ title, entries }: { title: string; entries: Array<[string, number]> }) {
    const max = Math.max(1, ...entries.map(([, count]) => count));
    return (
        <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-5">
            <h2 className="mb-4 font-medium">{title}</h2>
            <div className="space-y-3">
                {entries.length === 0 ? (
                    <div className="text-sm text-slate-400">暂无数据</div>
                ) : entries.map(([label, count]) => (
                    <div key={label}>
                        <div className="mb-1 flex justify-between text-sm">
                            <span className="text-slate-300">{label}</span>
                            <span className="text-slate-400">{count}</span>
                        </div>
                        <div className="h-2 overflow-hidden rounded-full bg-white/10">
                            <div className="h-full rounded-full bg-indigo-400" style={{ width: `${(count / max) * 100}%` }} />
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}
