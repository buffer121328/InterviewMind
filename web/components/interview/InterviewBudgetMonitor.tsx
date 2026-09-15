'use client';

import { useEffect, useRef, useState } from 'react';
import { Activity, AlertCircle, CheckCircle2, Clock3, Gauge, Loader2, TimerReset, XCircle } from 'lucide-react';
import { getAgentRun, getAgentRunBudget, streamAgentRunEvents } from '@/lib/api/agentRuns';
import type { AgentRun, InterviewBudgetAttempt, InterviewBudgetSnapshot, InterviewBudgetStage, InterviewBudgetStageStatus } from '@/lib/api/agentRunTypes';
import { applyAgentRunEvent, isTerminalAgentRunEvent } from '@/lib/agentRunEvents';
import {
    formatBudgetDuration,
    formatBudgetNumber,
    formatBudgetTokens,
    getBudgetFailureLabel,
    getBudgetSourceLabel,
    getBudgetStageLabel,
    getBudgetStatusLabel,
    getReviewerStagePairs,
    getVisibleStageMetrics,
    isQueuedBudgetStatus,
} from '@/lib/interviewBudgetMonitor';

interface InterviewBudgetMonitorProps {
    runId: string | null;
    /** The lifecycle poll already owned by the report dialog; false still performs one final snapshot read. */
    active?: boolean;
}

const STATUS_STYLES: Record<InterviewBudgetStageStatus, string> = {
    running: 'border-blue-200 bg-blue-50 text-blue-700',
    succeeded: 'border-emerald-200 bg-emerald-50 text-emerald-700',
    failed: 'border-red-200 bg-red-50 text-red-700',
    skipped: 'border-amber-200 bg-amber-50 text-amber-700',
    unknown: 'border-slate-200 bg-slate-50 text-slate-600',
};

function normalizeStatus(status: string): InterviewBudgetStageStatus {
    return status === 'running' || status === 'succeeded' || status === 'failed' || status === 'skipped'
        ? status
        : 'unknown';
}

function outcomeLabel(snapshot: InterviewBudgetSnapshot): string {
    if (isQueuedBudgetStatus(snapshot.status)) return '等待执行资源';
    if (snapshot.outcome === 'active' || snapshot.is_active) return '生成中';
    if (snapshot.outcome === 'recovered') return '已完成（含降级）';
    if (snapshot.outcome === 'failed' || snapshot.status === 'failed' || snapshot.status === 'cancelled') return '生成失败';
    if (snapshot.outcome === 'succeeded' || snapshot.status === 'succeeded' || snapshot.status === 'completed') return '已完成';
    return snapshot.status || '状态未知';
}

function outcomeIcon(snapshot: InterviewBudgetSnapshot) {
    if (isQueuedBudgetStatus(snapshot.status)) return <Clock3 className="h-4 w-4" />;
    if (snapshot.outcome === 'failed' || snapshot.status === 'failed' || snapshot.status === 'cancelled') return <XCircle className="h-4 w-4" />;
    if (!snapshot.is_active && (snapshot.outcome === 'succeeded' || snapshot.outcome === 'recovered')) return <CheckCircle2 className="h-4 w-4" />;
    return <Activity className="h-4 w-4" />;
}

function Metric({ label, value }: { label: string; value: string }) {
    return (
        <div className="rounded-lg bg-slate-50 px-3 py-2">
            <div className="text-[11px] text-slate-500">{label}</div>
            <div className="mt-0.5 text-sm font-medium text-slate-800">{value}</div>
        </div>
    );
}

function hasContextProtection(stage: InterviewBudgetStage): boolean {
    return stage.warning_types?.includes('context_protection') ?? false;
}

function formatContextProtectionSources(stage: InterviewBudgetStage): string {
    const sources = stage.context_protection_sources || [];
    return sources.length
        ? sources.map(getBudgetSourceLabel).join('、')
        : '具体来源未记录（历史运行）';
}

function AttemptDetails({ attempts }: { attempts: InterviewBudgetAttempt[] }) {
    if (!attempts.length) return null;
    return (
        <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5">
            <p className="text-xs font-medium text-slate-700">模型尝试明细</p>
            <ol className="mt-2 space-y-2">
                {attempts.map((attempt, index) => {
                    const failure = attempt.failure_type || attempt.failure_types[0];
                    const recovered = Boolean(failure) && attempt.status === 'failed';
                    return (
                        <li key={`${attempt.candidate_index ?? 'unknown'}-${attempt.fallback_index}-${attempt.attempt}-${index}`} className="rounded-md border border-white bg-white px-2.5 py-2 text-xs text-slate-600">
                            <div className="flex flex-wrap items-center justify-between gap-2">
                                <span className="font-medium text-slate-800">
                                    候选 {attempt.candidate_index ?? '-'} · fallback {attempt.fallback_index} · {attempt.model_name || '未知模型'}
                                </span>
                                <StageStatus status={attempt.status} />
                            </div>
                            <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
                                {failure && <span className={recovered ? 'text-amber-700' : 'text-red-700'}>{recovered ? '已恢复：' : '失败：'}{getBudgetFailureLabel(failure)}</span>}
                                {attempt.repair_outcome && <span>格式修复：{attempt.repair_outcome === 'completed' ? '完成' : attempt.repair_outcome === 'failed' ? '失败' : '进行中'}</span>}
                                {attempt.total_tokens !== null && <span>{formatBudgetNumber(attempt.total_tokens)} tokens</span>}
                                {attempt.duration_ms !== null && <span>{formatBudgetDuration(attempt.duration_ms)}</span>}
                            </div>
                        </li>
                    );
                })}
            </ol>
        </div>
    );
}

interface StageDetailsProps {
    stage: InterviewBudgetStage;
    title?: string;
    showSources?: boolean;
    showHeader?: boolean;
}

function StageDetails({ stage, title = getBudgetStageLabel(stage.stage), showSources = true, showHeader = true }: StageDetailsProps) {
    const status = normalizeStatus(stage.status);
    const failure = stage.primary_failure || stage.failure_types[0];
    const sources = Object.entries(stage.source_breakdown || {});
    const protectedContext = hasContextProtection(stage);
    const showContextSources = showSources && stage.kind === 'context';
    const metrics = getVisibleStageMetrics(stage);
    return (
        <div>
            {showHeader && (
                <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                        <p className="font-medium text-slate-900">{title}</p>
                        <p className="mt-1 break-all text-[11px] text-slate-400">{stage.stage}</p>
                    </div>
                    <StageStatus status={status} />
                </div>
            )}
            {metrics.length > 0 && <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                {metrics.map(metric => <Metric key={metric.label} {...metric} />)}
            </div>}
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
                <span>尝试 {formatBudgetNumber(stage.attempt_count)}</span>
                <span>完成 {formatBudgetNumber(stage.completed_count)}</span>
                {stage.retry_count > 0 && <span>重试 {formatBudgetNumber(stage.retry_count)}</span>}
                {stage.fallback_count > 0 && <span>fallback {formatBudgetNumber(stage.fallback_count)}</span>}
                {(stage.repair_count || 0) > 0 && <span>格式修复 {formatBudgetNumber(stage.repair_count || 0)}</span>}
                {(stage.usage_unavailable_count || 0) > 0 && <span>用量未返回 {formatBudgetNumber(stage.usage_unavailable_count || 0)}</span>}
                {stage.deadline_remaining_ms !== null && <span>剩余 {formatBudgetDuration(stage.deadline_remaining_ms)}</span>}
            </div>
            {showContextSources && sources.length > 0 && (
                <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5">
                    <p className="text-xs font-medium text-slate-700">上下文来源估算</p>
                    <div className="mt-2 flex flex-wrap gap-2">
                        {sources.map(([source, usage]) => (
                            <span key={source} className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs text-slate-600">
                                {getBudgetSourceLabel(source)} · 输入 {formatBudgetTokens(null, usage.estimated_input_tokens)} · {formatBudgetNumber(usage.input_chars)} 字符
                                {usage.estimated_raw_input_tokens !== undefined && usage.estimated_raw_input_tokens !== usage.estimated_input_tokens
                                    ? `（原始 ${formatBudgetTokens(null, usage.estimated_raw_input_tokens)} · ${formatBudgetNumber(usage.raw_input_chars ?? 0)} 字符）`
                                    : ''}
                            </span>
                        ))}
                    </div>
                </div>
            )}
            <AttemptDetails attempts={stage.attempts || []} />
            {stage.final_model_name && (
                <div className="mt-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
                    最终成功模型：<span className="font-semibold">{stage.final_model_name}</span>
                </div>
            )}
            {failure && !(stage.attempts || []).length && (
                <div className="mt-3 flex items-center gap-1.5 rounded-lg border border-amber-100 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                    <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                    阶段尝试结果：{getBudgetFailureLabel(failure)}
                </div>
            )}
            {protectedContext && (
                <div className="mt-3 flex items-center gap-1.5 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                    <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                    上下文保护触发位置：{title}；已裁剪：{formatContextProtectionSources(stage)}。这是保护性裁剪，不代表任务失败。
                </div>
            )}
        </div>
    );
}

function StageStatus({ status }: { status: InterviewBudgetStageStatus }) {
    return (
        <span className={`inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[status]}`}>
            {status === 'running' ? <Loader2 className="h-3 w-3 animate-spin" /> : status === 'failed' ? <AlertCircle className="h-3 w-3" /> : <CheckCircle2 className="h-3 w-3" />}
            {getBudgetStatusLabel(status)}
        </span>
    );
}

function StageCard({ stage }: { stage: InterviewBudgetStage }) {
    return <li className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"><StageDetails stage={stage} /></li>;
}

function ReportAssemblyPair({
    contextStage,
    generationStage,
}: {
    contextStage?: InterviewBudgetStage;
    generationStage?: InterviewBudgetStage;
}) {
    return (
        <li className="grid gap-3 xl:grid-cols-2">
            <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                {contextStage ? <StageDetails stage={contextStage} /> : <MissingStage title="报告上下文组装" />}
            </section>
            <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                {generationStage ? <StageDetails stage={generationStage} /> : <MissingStage title="报告生成" />}
            </section>
        </li>
    );
}

function MissingStage({ title }: { title: string }) {
    return <div className="flex min-h-24 items-center rounded-lg border border-dashed border-slate-200 bg-slate-50 px-3 text-xs leading-5 text-slate-500">尚未记录{title}阶段；后续运行会在此显示安全状态与指标。</div>;
}

function ReviewerStageCard({
    label,
    contextStage,
    reviewStage,
}: {
    label: string;
    contextStage?: InterviewBudgetStage;
    reviewStage?: InterviewBudgetStage;
}) {
    const contextTitle = `${label} · 上下文组装`;
    return (
        <li className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-medium text-slate-900">{label}</p>
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">组装上下文与评审</span>
            </div>
            <div className="mt-3 grid gap-3 xl:grid-cols-2">
                <section className="rounded-lg border border-slate-200 bg-slate-50/70 p-3">
                    <div className="flex items-center justify-between gap-2"><p className="text-xs font-semibold text-slate-700">上下文组装</p>{contextStage && <StageStatus status={normalizeStatus(contextStage.status)} />}</div>
                    <div className="mt-3">{contextStage ? <StageDetails stage={contextStage} title={contextTitle} showHeader={false} /> : <MissingStage title="上下文组装" />}</div>
                </section>
                <section className="rounded-lg border border-slate-200 bg-slate-50/70 p-3">
                    <div className="flex items-center justify-between gap-2"><p className="text-xs font-semibold text-slate-700">{label}</p>{reviewStage && <StageStatus status={normalizeStatus(reviewStage.status)} />}</div>
                    <div className="mt-3">{reviewStage ? <StageDetails stage={reviewStage} title={label} showSources={false} showHeader={false} /> : <MissingStage title={label} />}</div>
                </section>
            </div>
        </li>
    );
}

/** Shows safe per-stage token, elapsed-time and failure telemetry below an interview report. */
export function InterviewBudgetMonitor({ runId, active }: InterviewBudgetMonitorProps) {
    const [snapshot, setSnapshot] = useState<InterviewBudgetSnapshot | null>(null);
    const [run, setRun] = useState<AgentRun | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const lastEventSequence = useRef(0);

    useEffect(() => {
        if (!runId) {
            const resetTimer = window.setTimeout(() => {
                setSnapshot(null);
                setRun(null);
                setError(null);
                setLoading(false);
                lastEventSequence.current = 0;
            }, 0);
            return () => window.clearTimeout(resetTimer);
        }

        let cancelled = false;
        let stopped = active === false;
        let reconnectTimer: number | undefined;
        const controller = new AbortController();
        const load = async (showLoading = false) => {
            if (cancelled) return;
            if (showLoading) setLoading(true);
            try {
                const next = await getAgentRunBudget(runId);
                if (cancelled) return;
                setSnapshot(next);
                setError(null);
                if (!next.is_active) stopped = true;
            } catch {
                if (!cancelled) setError('预算监测暂不可用，报告内容不受影响');
            } finally {
                if (!cancelled && showLoading) setLoading(false);
            }
        };

        const subscribe = async () => {
            try {
                const current = await getAgentRun(runId);
                if (cancelled) return;
                setRun(current);
                if (['succeeded', 'failed', 'cancelled'].includes(current.status)) {
                    stopped = true;
                    return;
                }
                await streamAgentRunEvents(runId, event => {
                    if (cancelled || event.sequence <= lastEventSequence.current) return;
                    lastEventSequence.current = event.sequence;
                    setRun(previous => previous ? applyAgentRunEvent(previous, event) : previous);
                    if (isTerminalAgentRunEvent(event)) stopped = true;
                    void load();
                }, controller.signal, lastEventSequence.current);
            } catch (streamError) {
                if (!cancelled && !(streamError instanceof DOMException && streamError.name === 'AbortError')) {
                    setError('实时阶段同步暂不可用，正在使用轮询更新');
                }
            } finally {
                if (!cancelled && !stopped) reconnectTimer = window.setTimeout(() => void subscribe(), 1000);
            }
        };

        void load(true);
        void subscribe();
        const timer = window.setInterval(() => {
            if (!stopped) void load();
        }, 1500);
        return () => {
            cancelled = true;
            controller.abort();
            window.clearInterval(timer);
            if (reconnectTimer !== undefined) window.clearTimeout(reconnectTimer);
        };
    }, [active, runId]);

    const queued = isQueuedBudgetStatus(snapshot?.status);

    return (
        <section className="mx-auto w-[min(100%,900px)] px-4 pb-8" aria-live="polite">
            <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                        <div className="flex items-center gap-2 text-slate-900">
                            <Gauge className="h-5 w-5 text-orange-500" />
                            <h3 className="font-semibold">预算监测</h3>
                            {snapshot?.is_active && <span className="rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">实时</span>}
                        </div>
                        <p className="mt-1 text-xs text-slate-500">逐阶段记录上下文来源估算、实际模型 token、耗时、重试、保护提示和失败原因。</p>
                    </div>
                    {snapshot && (
                        <div className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${snapshot.outcome === 'failed' ? 'border-red-200 bg-red-50 text-red-700' : snapshot.outcome === 'recovered' ? 'border-amber-200 bg-amber-50 text-amber-700' : 'border-slate-200 bg-slate-50 text-slate-700'}`}>
                            {outcomeIcon(snapshot)}
                            {outcomeLabel(snapshot)}
                        </div>
                    )}
                </div>

                {loading && !snapshot ? (
                    <div className="flex items-center gap-2 py-8 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" />正在读取预算快照...</div>
                ) : !runId ? (
                    <p className="py-6 text-sm text-slate-500">本次报告没有可关联的生成任务，生成后会在这里显示预算。</p>
                ) : error && !snapshot ? (
                    <div className="mt-4 flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-3 text-sm text-amber-800"><AlertCircle className="h-4 w-4 shrink-0" />{error}</div>
                ) : snapshot ? (
                    <>
                        {error && <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">{error}</div>}
                        {queued ? (
                            <div className="mt-4 rounded-lg border border-blue-100 bg-blue-50 px-3 py-3 text-sm text-blue-800">
                                正在等待执行资源，模型尚未开始。本次已排队 {formatBudgetDuration(snapshot.elapsed_ms)}；没有模型 token、模型耗时或结构化输出结果可供统计。
                            </div>
                        ) : (
                            <>
                                <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
                                    <Metric label="任务耗时" value={formatBudgetDuration(snapshot.elapsed_ms)} />
                                    <Metric label="deadline / 剩余" value={`${formatBudgetDuration(snapshot.deadline_ms)} / ${formatBudgetDuration(snapshot.deadline_remaining_ms)}`} />
                                    <Metric label="最终报告已确认 token" value={formatBudgetTokens(snapshot.totals.total_tokens, snapshot.totals.model_estimated_input_tokens)} />
                                    <Metric label="上下文估算" value={formatBudgetTokens(null, snapshot.totals.context_estimated_input_tokens ?? null)} />
                                    <Metric label="模型耗时" value={formatBudgetDuration(snapshot.totals.model_duration_ms || snapshot.totals.duration_ms)} />
                                </div>
                                <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
                                    <span>输入字符 {formatBudgetNumber(snapshot.totals.input_chars)}</span>
                                    <span>全部阶段估算输入 token {formatBudgetNumber(snapshot.totals.estimated_input_tokens)}</span>
                                    <span>尝试 {formatBudgetNumber(snapshot.totals.attempt_count)}</span>
                                    <span>失败 {formatBudgetNumber(snapshot.totals.failed_count)}</span>
                                    {snapshot.totals.timeout_count > 0 && <span>超时 {formatBudgetNumber(snapshot.totals.timeout_count)}</span>}
                                    {snapshot.totals.fallback_count > 0 && <span>fallback {formatBudgetNumber(snapshot.totals.fallback_count)}</span>}
                                    {(snapshot.totals.repair_count || 0) > 0 && <span>格式修复 {formatBudgetNumber(snapshot.totals.repair_count || 0)}</span>}
                                    {(snapshot.totals.usage_unavailable_count || 0) > 0 && <span>用量未返回 {formatBudgetNumber(snapshot.totals.usage_unavailable_count || 0)}</span>}
                                    {(snapshot.totals.context_protection_count || 0) > 0 && <span>上下文保护 {formatBudgetNumber(snapshot.totals.context_protection_count)}</span>}
                                </div>
                            </>
                        )}
                        {run?.plan.length ? (
                            <ol className="mt-4 grid gap-2 sm:grid-cols-2">
                                {run.plan.map(step => <li key={step.id} className={`rounded-lg border px-3 py-2 text-xs ${STATUS_STYLES[normalizeStatus(step.status)]}`}><span className="font-medium">{step.title}</span><span className="ml-2">{getBudgetStatusLabel(normalizeStatus(step.status))}</span></li>)}
                            </ol>
                        ) : null}
                        {snapshot.primary_failure && (
                            <div className="mt-3 flex items-center gap-2 rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-xs text-red-700">
                                <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                                最近一次安全失败分类：{getBudgetFailureLabel(snapshot.primary_failure)}
                            </div>
                        )}
                        {snapshot.warning_types?.includes('context_protection') && (
                            <div className="mt-3 flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                                <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                                运行提示：{snapshot.stages.filter(hasContextProtection).map(stage => `${getBudgetStageLabel(stage.stage)}（${formatContextProtectionSources(stage)}）`).join('；') || '触发过上下文保护，但具体位置未记录（历史运行）'}。这是保护性裁剪，不代表任务失败。
                            </div>
                        )}
                        <div className="mt-5 flex items-center gap-2 text-sm font-medium text-slate-800">
                            <TimerReset className="h-4 w-4 text-orange-500" />阶段明细
                        </div>
                        {snapshot.stages.length ? (
                            <ol className="mt-3 space-y-3">
                                {(() => {
                                    const contextStage = snapshot.stages.find(stage => stage.stage === 'interview_report.context_assembly');
                                    const generationStage = snapshot.stages.find(stage => stage.stage === 'saving_report')
                                        ?? snapshot.stages.find(stage => stage.stage === 'session_report.narrative_composer');
                                    return contextStage || generationStage
                                        ? <ReportAssemblyPair contextStage={contextStage} generationStage={generationStage} />
                                        : null;
                                })()}
                                {getReviewerStagePairs().map(({ key, label, contextStage: contextStageName, reviewStage: reviewStageName }) => {
                                    const contextStage = snapshot.stages.find(stage => stage.stage === contextStageName);
                                    const reviewStage = snapshot.stages.find(stage => stage.stage === reviewStageName);
                                    return contextStage || reviewStage
                                        ? <ReviewerStageCard key={key} label={label} contextStage={contextStage} reviewStage={reviewStage} />
                                        : null;
                                })}
                                {snapshot.stages.filter(stage => (
                                    stage.stage !== 'interview_report.context_assembly'
                                    && stage.stage !== 'saving_report'
                                    && stage.stage !== 'session_report.narrative_composer'
                                    && !getReviewerStagePairs().some(pair => pair.contextStage === stage.stage || pair.reviewStage === stage.stage)
                                )).map(stage => <StageCard key={stage.stage} stage={stage} />)}
                            </ol>
                        ) : (
                            <p className="mt-3 rounded-lg border border-dashed border-slate-200 px-3 py-4 text-sm text-slate-500">{queued ? '任务已入队，正在等待 worker 领取；模型尚未开始。' : '报告业务阶段已实时展示；模型细分指标会在对应调用完成后补充。'}</p>
                        )}
                    </>
                ) : null}
                <div className="mt-4 flex items-center gap-1.5 text-[11px] text-slate-400"><Clock3 className="h-3 w-3" />只显示安全计数和分类，不显示 prompt、简历/JD 原文或供应商错误正文。</div>
            </div>
        </section>
    );
}
