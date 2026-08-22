'use client';

import { useMemo, useState, type ReactNode } from 'react';
import {
    CheckCircle2,
    ChevronDown,
    CircleAlert,
    CircleCheck,
    CircleX,
    FlaskConical,
    Gavel,
    ListChecks,
    UserCheck,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { PaginationControls } from '@/components/PaginationControls';
import type { EvaluationCaseRunDetail, EvaluationScore } from '@/lib/api/evaluations';
import {
    EVALUATION_SCORE_RULE_PAGE_SIZE,
    evaluationScoreOutcome,
    isEvaluationScoreNotApplicable,
    formatEvaluationScore,
    paginateEvaluationScores,
    summarizeEvaluationAnnotation,
    summarizeEvaluationCaseOutcome,
    summarizeEvaluationOutput,
    summarizeEvaluationScores,
    summarizeEvaluationScoreStatuses,
    summarizeEvaluationToolApplicability,
} from '@/lib/evaluationCaseDetail';
import { EvaluationTrajectory } from './EvaluationTrajectory';

interface Props {
    detail: EvaluationCaseRunDetail;
    candidateName: string;
    candidateVersion: string;
    onCandidateName: (value: string) => void;
    onCandidateVersion: (value: string) => void;
    onCreateCandidate: () => Promise<void>;
    includeJudges: boolean;
}

/** Renders a conclusion-first, collapsible drill-down for a single evaluation case. */
export function EvaluationCaseDetail({
    detail,
    candidateName,
    candidateVersion,
    onCandidateName,
    onCandidateVersion,
    onCreateCandidate,
    includeJudges,
}: Props) {
    const outcome = useMemo(() => summarizeEvaluationCaseOutcome(detail), [detail]);
    const scoreSummaries = useMemo(() => summarizeEvaluationScores(detail.scores), [detail.scores]);
    const scoreStatuses = useMemo(
        () => summarizeEvaluationScoreStatuses(detail, { includeJudges }),
        [detail, includeJudges],
    );
    const outputSummary = useMemo(() => summarizeEvaluationOutput(detail.actual_output), [detail.actual_output]);
    const toolApplicability = useMemo(() => summarizeEvaluationToolApplicability(detail), [detail]);
    const scoreRulesKey = `${detail.id}:${detail.scores.map((score) => `${score.id}:${score.status}:${score.reason ?? ''}`).join('|')}`;

    return <div className="mt-6 border-t pt-5">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div>
                <h4 className="font-semibold">案例详情 · {detail.case.case_key}</h4>
                <p className="text-xs text-slate-500">{detail.case.category} · {detail.case.severity} · 第 {detail.repetition_index + 1} 次运行</p>
            </div>
            <div className="flex flex-wrap gap-2 text-xs">
                <VerdictBadge outcome={outcome.hardGateTone} label={outcome.hardGateLabel} />
                <VerdictBadge outcome={outcome.reviewTone} label={outcome.reviewLabel} />
            </div>
        </div>

        <section className="mb-4 rounded-xl border border-slate-200 bg-gradient-to-br from-slate-50 to-white p-3">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                    <div className="text-xs font-medium text-slate-500">本次结论</div>
                    <div className="mt-1 flex items-center gap-2 text-base font-semibold text-slate-900">
                        <VerdictIcon outcome={outcome.statusTone} />
                        {outcome.statusLabel}
                    </div>
                </div>
                <div className="flex flex-wrap gap-2">
                    {outcome.metrics.map((metric) => <div key={metric.label} className="rounded-lg border bg-white px-2.5 py-1.5 text-xs"><span className="text-slate-500">{metric.label}</span><span className="ml-1 font-semibold text-slate-800">{metric.value}</span></div>)}
                </div>
            </div>
            <div className="mt-3 grid gap-2 md:grid-cols-3">
                {scoreStatuses.map((status) => <ScoreStatus key={status.key} status={status} />)}
            </div>
            <div className="mt-2 rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs text-slate-700"><span className="font-semibold">{toolApplicability.label}</span><span className="ml-1">{toolApplicability.detail}</span></div>
            {outcome.reviewReasons.length > 0 && <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-2 text-xs text-amber-900"><CircleAlert className="h-4 w-4 shrink-0" />{outcome.reviewReasons.map((reason) => <span key={reason} className="rounded-full bg-white/80 px-2 py-0.5">{reason}</span>)}</div>}
        </section>

        <div className="grid items-start gap-3 2xl:grid-cols-3">
            <DetailColumn title="输入与 Golden" summary={`${detail.case.tags.length} 个标签`} defaultOpen={false}>
                <JsonBlock label="案例输入" value={detail.case.input} />
                <JsonBlock label="预期输出 / 事实" value={detail.case.expected ?? {}} />
                <div className="flex flex-wrap gap-1">{detail.case.tags.map((tag) => <span key={tag} className="rounded-full bg-slate-100 px-2 py-1 text-[10px] text-slate-600">{tag}</span>)}</div>
            </DetailColumn>

            <DetailColumn title="执行轨迹" summary={detail.record.final_status ?? '查看运行步骤'} defaultOpen>
                <CollapsibleSection title="结构化执行轨迹" summary="点击展开安全轨迹节点" defaultOpen={false}><EvaluationTrajectory record={detail.record} scores={detail.scores} /></CollapsibleSection>
                <CollapsibleSection title="运行技术摘要" summary="错误、恢复次数与成本" defaultOpen={false}>
                    <JsonBlock label="运行记录摘要" value={{ final_status: detail.record.final_status, error: detail.record.error, recovery_count: detail.record.recovery_count, estimated_cost_usd: detail.record.estimated_cost_usd }} />
                </CollapsibleSection>
            </DetailColumn>

            <DetailColumn title="输出、评分与裁决" summary="结论、评分与复核" defaultOpen>
                <CollapsibleSection title="实际输出" summary={outputSummary} defaultOpen={false}>
                    <JsonBlock label="原始输出" value={detail.actual_output} />
                </CollapsibleSection>

                <section className="rounded-lg border bg-white p-2.5">
                    <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-slate-800"><ListChecks className="h-4 w-4 text-teal-700" />评分结果</div>
                    {scoreSummaries.length > 0 ? <div className="space-y-2">{scoreSummaries.map((summary) => <ScoreSummary key={summary.source} summary={summary} />)}</div> : <Empty text="暂无自动评分。" />}
                    {detail.scores.length > 0 && <ScoreRuleDetails key={scoreRulesKey} scores={detail.scores} />}
                </section>

                <section className="rounded-lg border bg-white p-2.5">
                    <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-slate-800"><Gavel className="h-4 w-4 text-violet-700" />裁决与人工复核</div>
                    <div className="mb-2 rounded-md bg-slate-50 px-2.5 py-2 text-xs text-slate-600">人工处理：<span className="font-medium text-slate-800">{reviewStatusLabel(detail.review_status)}</span>{detail.review_resolver_key ? ` · ${detail.review_resolver_key}` : ''}{detail.review_resolution_note ? ` · ${detail.review_resolution_note}` : ''}</div>
                    {detail.annotations.length === 0 ? <div className="rounded-md bg-slate-50 px-2.5 py-2 text-xs text-slate-600">暂无人工裁决，当前系统结论为：<span className="font-medium text-slate-800">{outcome.hardGateLabel}</span>。</div> : <div className="space-y-2">{detail.annotations.map((annotation) => <div key={annotation.id} className="rounded-md border bg-slate-50 p-2 text-xs"><div className="flex flex-wrap items-center justify-between gap-2"><span className="font-medium text-slate-800">{annotation.metric_name}</span><span className="rounded-full bg-white px-2 py-0.5 text-[10px] text-slate-600">{summarizeEvaluationAnnotation(annotation)}</span></div><div className="mt-1 text-slate-500">复核人：{annotation.reviewer_key} · 版本 {annotation.revision}</div><CollapsibleSection title="查看裁决依据" summary="标注值、说明与证据" defaultOpen={false} className="mt-2 border-t pt-2"><JsonBlock label="裁决信息" value={{ value: annotation.value, labels: annotation.labels, confidence: annotation.confidence, comment: annotation.comment, evidence_spans: annotation.evidence_spans }} /></CollapsibleSection></div>)}</div>}
                </section>
            </DetailColumn>
        </div>

        <div className="mt-3 rounded-xl border border-dashed border-teal-200 bg-teal-50/50 p-3">
            <div className="flex flex-col justify-between gap-3 md:flex-row md:items-end">
                <div><div className="flex items-center gap-2 text-sm font-medium text-teal-900"><FlaskConical className="h-4 w-4" />失败案例沉淀</div><p className="mt-1 text-xs text-teal-700">创建新的 Candidate Dataset Version，不修改已锁定版本。</p></div>
                <div className="grid gap-2 sm:grid-cols-[220px_150px_auto]"><Input value={candidateName} onChange={(event) => onCandidateName(event.target.value)} placeholder="Dataset 名称" /><Input value={candidateVersion} onChange={(event) => onCandidateVersion(event.target.value)} placeholder="版本" /><Button onClick={() => void onCreateCandidate()}><CheckCircle2 />加入回归集</Button></div>
            </div>
        </div>
    </div>;
}

function DetailColumn({ title, summary, defaultOpen, children }: { title: string; summary: string; defaultOpen: boolean; children: ReactNode }) {
    return <section className="min-w-0 self-start rounded-xl border bg-slate-50/60 p-3"><CollapsibleSection title={title} summary={summary} defaultOpen={defaultOpen}>{children}</CollapsibleSection></section>;
}

function CollapsibleSection({ title, summary, defaultOpen, className = '', children, onOpenChange }: { title: string; summary: string; defaultOpen: boolean; className?: string; children: ReactNode; onOpenChange?: (open: boolean) => void }) {
    const [open, setOpen] = useState(defaultOpen);
    const toggle = () => setOpen((current) => {
        const next = !current;
        onOpenChange?.(next);
        return next;
    });
    return <div className={className}><button type="button" className="flex w-full items-start justify-between gap-3 text-left" onClick={toggle} aria-expanded={open}><span><span className="block text-sm font-semibold text-slate-800">{title}</span><span className="mt-0.5 block text-xs font-normal text-slate-500">{summary}</span></span><ChevronDown className={`mt-0.5 h-4 w-4 shrink-0 text-slate-500 transition-transform ${open ? 'rotate-180' : ''}`} /></button>{open && <div className="mt-3">{children}</div>}</div>;
}

function ScoreStatus({ status }: { status: ReturnType<typeof summarizeEvaluationScoreStatuses>[number] }) {
    return <div className={`rounded-lg border px-2.5 py-2 text-xs ${toneClasses(status.tone)}`}>
        <div className="font-semibold">{status.label}</div>
        <div className="mt-1 leading-5">{status.detail}</div>
    </div>;
}

function ScoreSummary({ summary }: { summary: ReturnType<typeof summarizeEvaluationScores>[number] }) {
    const primaryOutcome = summary.failed > 0 ? 'failed' : summary.review > 0 ? 'review' : summary.passed > 0 ? 'passed' : 'neutral';
    return <div className={`rounded-md border p-2 ${toneClasses(primaryOutcome)}`}><div className="flex items-center justify-between gap-2 text-xs"><span className="font-semibold">{summary.label}</span><span>{summary.scores.length} 项</span></div><div className="mt-1.5 flex flex-wrap gap-1.5 text-[11px]">{summary.passed > 0 && <span className="rounded bg-white/80 px-1.5 py-0.5">通过 {summary.passed}</span>}{summary.failed > 0 && <span className="rounded bg-white/80 px-1.5 py-0.5">未通过 {summary.failed}</span>}{summary.review > 0 && <span className="rounded bg-white/80 px-1.5 py-0.5">待复核 {summary.review}</span>}{summary.notApplicable > 0 && <span className="rounded bg-white/80 px-1.5 py-0.5">不适用 {summary.notApplicable}</span>}{summary.hardGateFailures > 0 && <span className="rounded bg-red-100 px-1.5 py-0.5 text-red-800">硬门禁异常 {summary.hardGateFailures}</span>}</div></div>;
}

function ScoreRuleDetails({ scores }: { scores: EvaluationScore[] }) {
    const [page, setPage] = useState(1);
    const pageData = useMemo(() => paginateEvaluationScores(scores, page), [scores, page]);

    return <CollapsibleSection title="查看全部评分规则" summary={`${scores.length} 项评分明细 · 每页 ${EVALUATION_SCORE_RULE_PAGE_SIZE} 条`} defaultOpen={false} className="mt-2 border-t pt-2" onOpenChange={(open) => { if (!open) setPage(1); }}>
        <div className="space-y-1.5">{pageData.scores.map((score) => <ScoreDetail key={score.id} score={score} />)}</div>
        {pageData.totalPages > 1 && <PaginationControls page={pageData.page} total={scores.length} pageSize={EVALUATION_SCORE_RULE_PAGE_SIZE} onPageChange={setPage} className="mt-3" />}
    </CollapsibleSection>;
}

function ScoreDetail({ score }: { score: EvaluationScore }) {
    const outcome = isEvaluationScoreNotApplicable(score.status) ? 'neutral' : evaluationScoreOutcome(score.status);
    return <div className={`rounded-md border p-2 text-xs ${toneClasses(outcome)}`}><div className="flex items-center justify-between gap-2"><span className="font-medium">{score.metric_name}</span><span>{formatEvaluationScore(score)}</span></div><div className="mt-1 text-[11px] opacity-80">{score.hard_gate ? '硬门禁 · ' : ''}{score.metric_version}{score.reason ? ` · ${score.reason}` : ''}</div></div>;
}

function reviewStatusLabel(status: string): string { return ({ not_required: '无需处理', pending: '待处理', approved: '人工确认通过', rejected: '人工确认不通过', waived: '已豁免', rerun_requested: '待重跑' } as Record<string, string>)[status] ?? status; }
function VerdictBadge({ outcome, label }: { outcome: ReturnType<typeof evaluationScoreOutcome>; label: string }) { return <span className={`inline-flex items-center rounded-full px-2 py-1 ${toneClasses(outcome)}`}>{label}</span>; }
function VerdictIcon({ outcome }: { outcome: ReturnType<typeof evaluationScoreOutcome> }) { return outcome === 'passed' ? <CircleCheck className="h-5 w-5 text-emerald-600" /> : outcome === 'failed' ? <CircleX className="h-5 w-5 text-red-600" /> : <UserCheck className="h-5 w-5 text-amber-600" />; }
function toneClasses(outcome: ReturnType<typeof evaluationScoreOutcome> | 'neutral'): string { return outcome === 'passed' ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : outcome === 'failed' ? 'border-red-200 bg-red-50 text-red-800' : outcome === 'neutral' ? 'border-slate-200 bg-slate-50 text-slate-700' : 'border-amber-200 bg-amber-50 text-amber-800'; }
function JsonBlock({ label, value }: { label: string; value: unknown }) { return <div><div className="mb-1 text-xs font-medium text-slate-600">{label}</div><pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-slate-950 p-3 text-[11px] leading-5 text-emerald-200">{JSON.stringify(value ?? null, null, 2)}</pre></div>; }
function Empty({ text }: { text: string }) { return <div className="rounded-md bg-slate-50 px-2.5 py-2 text-center text-xs text-slate-500">{text}</div>; }
