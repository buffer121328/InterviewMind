'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, Loader2, Play, RefreshCw, ShieldCheck, XCircle } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { cancelAgentRun, retryAgentRun, type AgentRun } from '@/lib/api/agentRuns';
import {
    evaluationApi,
    type EvaluationDataset,
    type InterviewEvaluationCapability,
    type InterviewEvaluationDraftAnnotation,
    type InterviewEvaluationSourceSession,
} from '@/lib/api/evaluations';
import { getRequestApiConfig } from '@/store/interviewFacade';
import {
    buildInterviewDatasetConfirmation,
    interviewEvaluationErrorMessage,
    interviewEvaluationSourceView,
    canConfirmInterviewDataset,
    initializeInterviewReviewCases,
    interviewDraftResult,
    parseInterviewQualityRubric,
    type InterviewEvaluationReviewCase as ReviewCase,
} from '@/lib/interviewHistoryEvaluation';
import { ProductionHistoryEvaluationPanel } from './ProductionHistoryEvaluationPanel';

interface Props {
    sessionId: string;
    completed: boolean;
    onOpenEvaluationCenter?: (datasetId: string) => void;
}

const ACTIVE = new Set(['queued', 'retrying', 'running', 'cancel_requested']);
const REASON_LABELS: Record<string, string> = {
    missing_persisted_attempt: '该历史会话没有持久化逐题回答记录',
    missing_interview_plan: '缺少可复现的面试计划',
    missing_resume_context: '缺少简历上下文',
    missing_job_context: '缺少岗位描述',
    unsupported_round_type: '面试轮次类型不受支持',
};

function textList(value: unknown[]): string {
    return value.map(item => typeof item === 'string' ? item : JSON.stringify(item)).join('\n');
}

function parseTextList(value: string): string[] {
    return value.split('\n').map(item => item.trim()).filter(Boolean);
}

/** Selects persisted interview attempts, monitors drafting, and enforces per-case human review. */
export function InterviewHistoryEvaluationPanel({ sessionId, completed, onOpenEvaluationCenter }: Props) {
    const [source, setSource] = useState<InterviewEvaluationSourceSession | null>(null);
    const [selected, setSelected] = useState<number[]>([]);
    const [capability, setCapability] = useState<InterviewEvaluationCapability>('interview_turn');
    const [run, setRun] = useState<AgentRun | null>(null);
    const [cases, setCases] = useState<ReviewCase[]>([]);
    const [loading, setLoading] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const [confirming, setConfirming] = useState(false);
    const [datasetName, setDatasetName] = useState('历史面试评测集');
    const [datasetVersion, setDatasetVersion] = useState('v1');
    const [created, setCreated] = useState<EvaluationDataset | null>(null);
    const [retryingFailed, setRetryingFailed] = useState(false);
    const pollRef = useRef<AbortController | null>(null);

    const loadSource = useCallback(async () => {
        if (!completed) return;
        setLoading(true);
        try {
            const result = await evaluationApi.interviewHistorySources(sessionId);
            const current = result.items.find(item => item.session_id === sessionId) || null;
            setSource(current);
            setSelected(current?.attempts.map(item => item.attempt_id) || []);
        } catch (error) {
            toast.error(interviewEvaluationErrorMessage(error, '读取可评测问答失败'));
        } finally {
            setLoading(false);
        }
    }, [completed, sessionId]);

    useEffect(() => {
        const timer = window.setTimeout(() => void loadSource(), 0);
        return () => window.clearTimeout(timer);
    }, [loadSource]);

    useEffect(() => () => pollRef.current?.abort(), []);

    const monitor = useCallback(async (runId: string) => {
        pollRef.current?.abort();
        const controller = new AbortController();
        pollRef.current = controller;
        while (!controller.signal.aborted) {
            const current = await evaluationApi.getInterviewHistoryDraft(runId);
            setRun(current);
            if (!ACTIVE.has(current.status)) {
                const result = interviewDraftResult(current);
                setCases(initializeInterviewReviewCases(result));
                return;
            }
            await new Promise(resolve => window.setTimeout(resolve, 1200));
        }
    }, []);

    const startDraft = useCallback(async () => {
        if (!selected.length) return;
        const apiConfig = getRequestApiConfig();
        if (!apiConfig) {
            toast.error('请先在设置中保存主模型与 Fast 模型配置');
            return;
        }
        setSubmitting(true);
        setCreated(null);
        try {
            const createdRun = await evaluationApi.createInterviewHistoryDraft({
                attempt_ids: selected,
                capability,
                api_config: apiConfig as Record<string, unknown>,
            });
            setRun(createdRun);
            await monitor(createdRun.run_id);
        } catch (error) {
            toast.error(interviewEvaluationErrorMessage(error, '提交整理任务失败'));
        } finally {
            setSubmitting(false);
        }
    }, [capability, monitor, selected]);

    const updateCase = useCallback((attemptId: number, updater: (item: ReviewCase) => ReviewCase) => {
        setCases(current => current.map(item => item.attempt_id === attemptId ? updater(item) : item));
    }, []);

    const includedCases = useMemo(() => cases.filter(item => item.included), [cases]);
    const canConfirm = Boolean(run && canConfirmInterviewDataset(cases));
    const failedAttemptIds = useMemo(
        () => cases.filter(item => item.validation_status === 'failed').map(item => item.attempt_id),
        [cases],
    );

    const retryFailedCases = useCallback(async (attemptIds: number[]) => {
        if (!run || !attemptIds.length) return;
        const apiConfig = getRequestApiConfig();
        if (!apiConfig) {
            toast.error('请先在设置中保存可用的 Fast 模型配置');
            return;
        }
        setRetryingFailed(true);
        try {
            const retried = await evaluationApi.retryInterviewHistoryDraftCases(run.run_id, {
                attempt_ids: attemptIds,
                api_config: apiConfig as Record<string, unknown>,
            });
            setRun(retried);
            setCases([]);
            await monitor(retried.run_id);
        } catch (error) {
            toast.error(interviewEvaluationErrorMessage(error, '重试失败案例失败'));
        } finally {
            setRetryingFailed(false);
        }
    }, [monitor, run]);

    const confirm = useCallback(async () => {
        if (!run || !canConfirm) return;
        setConfirming(true);
        try {
            const dataset = await evaluationApi.confirmInterviewHistoryDraft(
                run.run_id,
                buildInterviewDatasetConfirmation(datasetName, datasetVersion, cases),
            );
            setCreated(dataset);
            toast.success(`已创建草稿数据集 ${dataset.name}@${dataset.version}`);
        } catch (error) {
            toast.error(interviewEvaluationErrorMessage(error, '确认创建数据集失败'));
        } finally {
            setConfirming(false);
        }
    }, [canConfirm, cases, datasetName, datasetVersion, run]);

    const sourceView = interviewEvaluationSourceView({
        completed,
        loading,
        source,
        ineligibilityMessage: source ? REASON_LABELS[source.ineligibility_reason || ''] : undefined,
    });
    if (sourceView.state !== 'ready') return <div className="space-y-4 p-6">
        {completed && <ProductionHistoryEvaluationPanel capability="interview_planner" sourceId={sessionId} />}
        <Empty text={sourceView.message} loading={sourceView.state === 'loading'} />
    </div>;
    if (!source) return null;

    const draftResult = interviewDraftResult(run);
    return <div className="space-y-5 p-6">
        <ProductionHistoryEvaluationPanel capability="interview_planner" sourceId={sessionId} />
        <section className="rounded-xl border border-teal-200 bg-teal-50/60 p-4">
            <div className="flex items-start gap-3">
                <ShieldCheck className="mt-0.5 h-5 w-5 text-teal-700" />
                <div className="text-sm text-teal-900">
                    <p className="font-semibold">安全整理流程</p>
                    <p className="mt-1 text-teal-700">源问答先由后端确定性脱敏；模型只生成评测约束。创建前必须逐案例人工审阅，确认后只生成 draft Candidate Dataset。</p>
                </div>
            </div>
        </section>

        {!draftResult && <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <div><h3 className="font-semibold">选择已完成问答</h3><p className="text-xs text-slate-500">已找到 {source.eligible_attempt_count} 条持久化回答，最多选择 50 条。</p></div>
                <select className="h-9 rounded-md border px-3 text-sm" value={capability} onChange={event => setCapability(event.target.value as InterviewEvaluationCapability)}>
                    <option value="interview_turn">面试追问与反馈</option>
                    <option value="interview_scoring">回答评分</option>
                </select>
            </div>
            <div className="space-y-2">{source.attempts.map(attempt => <label key={attempt.attempt_id} className="flex gap-3 rounded-lg border p-3 text-sm">
                <Checkbox checked={selected.includes(attempt.attempt_id)} onCheckedChange={checked => setSelected(current => checked ? [...current, attempt.attempt_id] : current.filter(id => id !== attempt.attempt_id))} />
                <span><strong>Q{attempt.sequence}</strong> · {attempt.question}</span>
            </label>)}</div>
            <Button onClick={() => void startDraft()} disabled={!selected.length || submitting}>
                {submitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}自动脱敏并整理 JSON 草稿
            </Button>
        </section>}

        {run && <section className="rounded-xl border border-slate-200 bg-white p-4 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <div><strong>{run.title}</strong><p className="text-xs text-slate-500">{run.stage} · 第 {run.attempts}/{run.max_attempts} 次尝试</p></div>
                <div className="flex gap-2">
                    {run.can_cancel && <Button size="sm" variant="outline" onClick={async () => setRun(await cancelAgentRun(run.run_id))}>取消</Button>}
                    {run.can_retry && <Button size="sm" variant="outline" onClick={async () => { const retried = await retryAgentRun(run.run_id); setRun(retried); await monitor(retried.run_id); }}><RefreshCw className="mr-1 h-3.5 w-3.5" />整批重试</Button>}
                    {run.status === 'succeeded' && failedAttemptIds.length > 1 && <Button size="sm" variant="outline" disabled={retryingFailed} onClick={() => void retryFailedCases(failedAttemptIds)}>{retryingFailed ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="mr-1 h-3.5 w-3.5" />}重试全部 {failedAttemptIds.length} 个失败案例</Button>}
                </div>
            </div>
            {run.error_message && <p className="mt-3 rounded bg-red-50 p-2 text-red-700">{run.error_message}</p>}
        </section>}

        {draftResult && <>
            <div className="grid gap-3 sm:grid-cols-3"><Metric label="已选择" value={draftResult.selected_count} /><Metric label="可审阅" value={draftResult.valid_count} /><Metric label="失败" value={draftResult.failed_count} /></div>
            <div className="space-y-4">{cases.map(item => <ReviewCard key={item.attempt_id} item={item} retrying={retryingFailed} onRetry={() => void retryFailedCases([item.attempt_id])} update={updater => updateCase(item.attempt_id, updater)} />)}</div>
            <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-5">
                <div className="grid gap-3 sm:grid-cols-2"><Input value={datasetName} onChange={event => setDatasetName(event.target.value)} placeholder="Dataset 名称" /><Input value={datasetVersion} onChange={event => setDatasetVersion(event.target.value)} placeholder="版本，如 v1" /></div>
                <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-950 p-3 text-[11px] text-emerald-200">{JSON.stringify({ name: datasetName, version: datasetVersion, source: `interview_history:${run?.run_id}`, cases: includedCases }, null, 2)}</pre>
                <div className="flex flex-wrap items-center gap-3"><Button disabled={!canConfirm || confirming || !datasetName.trim() || !datasetVersion.trim()} onClick={() => void confirm()}>{confirming && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}确认创建草稿数据集</Button>{!canConfirm && <span className="text-xs text-amber-700">所有纳入案例都必须有效并勾选“已人工审阅”。</span>}</div>
                {created && <div className="flex items-center justify-between rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800"><span><CheckCircle2 className="mr-2 inline h-4 w-4" />{created.name}@{created.version} 已创建，状态：{created.status}</span>{onOpenEvaluationCenter && <Button size="sm" variant="outline" onClick={() => onOpenEvaluationCenter(created.id)}>前往评测中心</Button>}</div>}
            </section>
        </>}
    </div>;
}

function ReviewCard({ item, retrying, onRetry, update }: { item: ReviewCase; retrying: boolean; onRetry: () => void; update: (updater: (item: ReviewCase) => ReviewCase) => void }) {
    const annotation = item.annotation;
    const [rubricText, setRubricText] = useState(() => JSON.stringify(annotation?.quality_rubric || {}, null, 2));
    return <section className={`rounded-xl border bg-white p-5 ${item.validation_status === 'valid' ? 'border-slate-200' : 'border-red-200'}`}>
        <div className="flex flex-wrap items-start justify-between gap-3"><div><div className="flex items-center gap-2 font-semibold">{item.validation_status === 'valid' ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : <XCircle className="h-4 w-4 text-red-600" />}Attempt #{item.attempt_id}</div><p className="mt-1 text-xs text-slate-500">{item.model.model || '未调用模型'}{typeof item.model.fallback_index === 'number' && item.model.fallback_index > 0 ? ` · fallback ${item.model.fallback_index}` : ''}</p></div><label className="flex items-center gap-2 text-sm"><Checkbox checked={item.included} disabled={item.validation_status !== 'valid'} onCheckedChange={checked => update(current => ({ ...current, included: Boolean(checked), reviewed: false }))} />纳入数据集</label></div>
        {item.failure_reason && <div className="mt-3 flex items-center justify-between gap-3 rounded bg-red-50 p-2 text-sm text-red-700"><span>{item.failure_reason}</span><Button size="sm" variant="outline" disabled={retrying} onClick={onRetry}><RefreshCw className="mr-1 h-3.5 w-3.5" />仅重试此案例</Button></div>}
        <div className="mt-4 grid gap-3 lg:grid-cols-2"><ReadOnly label="源问题" value={item.question} /><ReadOnly label="源回答（已脱敏）" value={item.answer} /></div>
        <details className="mt-3"><summary className="cursor-pointer text-xs font-medium text-slate-600">查看冻结 input 与 evidence</summary><pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded bg-slate-950 p-3 text-[11px] text-emerald-200">{JSON.stringify({ input: item.frozen_input, evidence_refs: item.evidence_refs, source_hash: item.source_hash }, null, 2)}</pre></details>
        {annotation && <div className="mt-4 grid gap-3 lg:grid-cols-2">
            <Field label="Case Key"><Input value={annotation.case_key} onChange={event => update(current => ({ ...current, reviewed: false, annotation: current.annotation ? { ...current.annotation, case_key: event.target.value } : null }))} /></Field>
            <Field label="Category"><Input value={annotation.category} onChange={event => update(current => ({ ...current, reviewed: false, annotation: current.annotation ? { ...current.annotation, category: event.target.value } : null }))} /></Field>
            <Field label="Expected Facts（每行一条）"><Textarea value={textList(annotation.expected_facts)} onChange={event => update(current => ({ ...current, reviewed: false, annotation: current.annotation ? { ...current.annotation, expected_facts: parseTextList(event.target.value) } : null }))} /></Field>
            <Field label="Forbidden Claims（每行一条）"><Textarea value={textList(annotation.forbidden_claims)} onChange={event => update(current => ({ ...current, reviewed: false, annotation: current.annotation ? { ...current.annotation, forbidden_claims: parseTextList(event.target.value) } : null }))} /></Field>
            <Field label="Tags（逗号分隔）"><Input value={annotation.tags.join(', ')} onChange={event => update(current => ({ ...current, reviewed: false, annotation: current.annotation ? { ...current.annotation, tags: event.target.value.split(',').map(tag => tag.trim()).filter(Boolean) } : null }))} /></Field>
            <Field label="Severity"><select className="h-10 rounded-md border px-3 text-sm" value={annotation.severity} onChange={event => update(current => ({ ...current, reviewed: false, annotation: current.annotation ? { ...current.annotation, severity: event.target.value as InterviewEvaluationDraftAnnotation['severity'] } : null }))}><option value="low">low</option><option value="medium">medium</option><option value="high">high</option><option value="critical">critical</option></select></Field>
            <Field label="Quality Rubric JSON"><Textarea value={rubricText} onChange={event => {
                const value = event.target.value;
                setRubricText(value);
                try {
                    const qualityRubric = parseInterviewQualityRubric(value);
                    update(current => ({ ...current, review_error: null, reviewed: false, annotation: current.annotation ? { ...current.annotation, quality_rubric: qualityRubric } : null }));
                } catch {
                    update(current => ({ ...current, review_error: 'Quality Rubric JSON 格式无效', reviewed: false }));
                }
            }} />{item.review_error && <span className="text-red-600">{item.review_error}</span>}</Field>
            <Field label="模型说明"><Textarea value={annotation.explanation} onChange={event => update(current => ({ ...current, reviewed: false, annotation: current.annotation ? { ...current.annotation, explanation: event.target.value } : null }))} /></Field>
        </div>}
        <label className="mt-4 flex items-center gap-2 text-sm font-medium"><Checkbox checked={item.reviewed} disabled={!item.included || item.validation_status !== 'valid'} onCheckedChange={checked => update(current => ({ ...current, reviewed: Boolean(checked) }))} />已人工审阅源问答、脱敏 input 和生成约束</label>
    </section>;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) { return <label className="grid gap-1 text-xs font-medium text-slate-600"><span>{label}</span>{children}</label>; }
function ReadOnly({ label, value }: { label: string; value: string }) { return <div className="rounded-lg bg-slate-50 p-3"><div className="text-xs font-medium text-slate-500">{label}</div><p className="mt-1 whitespace-pre-wrap text-sm text-slate-800">{value}</p></div>; }
function Metric({ label, value }: { label: string; value: number }) { return <div className="rounded-xl border bg-white p-4"><div className="text-xs text-slate-500">{label}</div><div className="mt-1 text-2xl font-semibold">{value}</div></div>; }
function Empty({ text, loading = false }: { text: string; loading?: boolean }) { return <div className="flex min-h-72 items-center justify-center gap-2 p-8 text-sm text-slate-500">{loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <AlertTriangle className="h-4 w-4 text-amber-500" />}{text}</div>; }
