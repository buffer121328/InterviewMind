'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
    Download,
    ExternalLink,
    Loader2,
    Play,
    RefreshCw,
    RotateCcw,
    Square,
    UserCheck,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import type {
    EvaluationCaseRun,
    EvaluationCaseRunDetail,
    EvaluationCaseRunFilters,
    EvaluationDatasetDetail,
    EvaluationApprovalStatus,
    EvaluationRun,
    EvaluationSuite,
    EvaluationToolEffect,
} from '@/lib/api/evaluations';
import { downloadEvaluationReport, evaluationApi } from '@/lib/api/evaluations';
import { runProgress } from '@/lib/evaluationMetrics';
import { toast } from 'sonner';
import { EvaluationCaseDetail } from './EvaluationCaseDetail';

interface Props {
    runs: EvaluationRun[];
    suites: EvaluationSuite[];
    focusRunId: string | null;
    onRefresh: () => Promise<void>;
    onOpenAnnotations: () => void;
}

interface RunForm {
    suite_id: string;
    model_config_hash: string;
    prompt_name: string;
    prompt_version: string;
    baseline_run_id: string;
    repetition_count: string;
    max_concurrency: string;
    max_budget_usd: string;
    human_review_rate: string;
    include_judges: boolean;
}

/** Provides bounded run creation, lifecycle actions and a three-column case drill-down. */
export function EvaluationRunsPanel({ runs, suites, focusRunId, onRefresh, onOpenAnnotations }: Props) {
    const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
    const [cases, setCases] = useState<EvaluationCaseRun[]>([]);
    const [selectedCaseRunId, setSelectedCaseRunId] = useState<string | null>(null);
    const [caseDetail, setCaseDetail] = useState<EvaluationCaseRunDetail | null>(null);
    const [dataset, setDataset] = useState<EvaluationDatasetDetail | null>(null);
    const [selectedCaseIds, setSelectedCaseIds] = useState<Set<string>>(() => new Set());
    const [caseFilters, setCaseFilters] = useState<EvaluationCaseRunFilters>({});
    const [traceNotice, setTraceNotice] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const [detailBusy, setDetailBusy] = useState(false);
    const [candidateName, setCandidateName] = useState('evaluation-regression');
    const [candidateVersion, setCandidateVersion] = useState(() => new Date().toISOString().slice(0, 10).replaceAll('-', ''));
    const [form, setForm] = useState<RunForm>(() => promptCandidateForm());
    const effectiveSuiteId = form.suite_id || suites[0]?.id || '';
    const selected = useMemo(() => runs.find((run) => run.id === selectedRunId) ?? null, [runs, selectedRunId]);
    const selectedSuite = useMemo(() => suites.find((suite) => suite.id === effectiveSuiteId) ?? null, [effectiveSuiteId, suites]);
    const visibleDataset = dataset?.id === selectedSuite?.dataset_version_id ? dataset : null;

    const loadCaseDetail = useCallback(async (caseRunId: string) => {
        setSelectedCaseRunId(caseRunId);
        setDetailBusy(true);
        try {
            setCaseDetail(await evaluationApi.caseRun(caseRunId));
        } catch (error) {
            toast.error(error instanceof Error ? error.message : '加载案例详情失败');
        } finally {
            setDetailBusy(false);
        }
    }, []);

    /** Loads owner-scoped case summaries and keeps the active governance filters server-side. */
    const loadCases = useCallback(async (runId: string, filters: EvaluationCaseRunFilters = {}) => {
        setSelectedRunId(runId);
        setSelectedCaseRunId(null);
        setCaseDetail(null);
        setTraceNotice(null);
        try {
            const result = await evaluationApi.caseRuns(runId, filters);
            setCases(result.items);
            if (result.items[0]) void loadCaseDetail(result.items[0].id);
        } catch (error) {
            toast.error(error instanceof Error ? error.message : '加载案例失败');
        }
    }, [loadCaseDetail]);

    useEffect(() => {
        const target = focusRunId ?? (!selectedRunId ? runs[0]?.id : null);
        if (!target || target === selectedRunId) return;
        const timer = window.setTimeout(() => void loadCases(target, caseFilters), 0);
        return () => window.clearTimeout(timer);
    }, [caseFilters, focusRunId, loadCases, runs, selectedRunId]);

    useEffect(() => {
        if (!selectedRunId) return;
        const timer = window.setTimeout(() => void loadCases(selectedRunId, caseFilters), 0);
        return () => window.clearTimeout(timer);
    }, [caseFilters, loadCases, selectedRunId]);

    useEffect(() => {
        if (!selectedSuite) {
            return;
        }
        let cancelled = false;
        void evaluationApi.getDataset(selectedSuite.dataset_version_id).then((result) => {
            if (!cancelled) {
                setDataset(result);
                setSelectedCaseIds(new Set());
            }
        }).catch((error) => { if (!cancelled) toast.error(error instanceof Error ? error.message : '加载数据集案例失败'); });
        return () => { cancelled = true; };
    }, [selectedSuite]);

    async function createRun() {
        if (!effectiveSuiteId) return toast.error('请先创建并选择评测套件');
        if (!form.model_config_hash.trim()) return toast.error('模型配置哈希不能为空');
        const productionBaseline = runs.find((run) => run.status === 'succeeded' && run.prompt_name === form.prompt_name && String(run.prompt_version) !== form.prompt_version);
        const baselineRunId = form.baseline_run_id === '__production__' ? productionBaseline?.id ?? null : form.baseline_run_id || null;
        if (form.baseline_run_id === '__production__' && !baselineRunId) return toast.error('没有找到可用的 Production 基线运行');
        setBusy(true);
        try {
            await evaluationApi.createRun({
                suite_id: effectiveSuiteId,
                agent_version: 'production',
                prompt_name: form.prompt_name || null,
                prompt_version: form.prompt_version || null,
                baseline_run_id: baselineRunId,
                model_config_hash: form.model_config_hash,
                api_config: {},
                repetition_count: Number(form.repetition_count),
                max_concurrency: Number(form.max_concurrency),
                max_budget_usd: Number(form.max_budget_usd),
                case_ids: [...selectedCaseIds],
                include_judges: form.include_judges,
                human_review_rate: Number(form.human_review_rate) / 100,
            });
            localStorage.removeItem('evaluationPromptCandidate');
            toast.success(selectedCaseIds.size ? `已提交 ${selectedCaseIds.size} 个选中案例` : '评测任务已进入 AgentRun 队列');
            await onRefresh();
        } catch (error) {
            toast.error(error instanceof Error ? error.message : '创建失败');
        } finally {
            setBusy(false);
        }
    }

    async function action(kind: 'cancel' | 'retry' | 'review') {
        if (!selected) return;
        setBusy(true);
        try {
            if (kind === 'cancel') await evaluationApi.cancelRun(selected.id);
            if (kind === 'retry') await evaluationApi.retryRun(selected.id);
            if (kind === 'review') {
                const result = await evaluationApi.requestReview(selected.id);
                toast.success(`已将 ${result.queued_count} 个失败案例加入人工复核`);
                onOpenAnnotations();
            } else {
                toast.success(kind === 'cancel' ? '已请求取消' : '失败案例已进入重试');
            }
            await onRefresh();
        } catch (error) {
            toast.error(error instanceof Error ? error.message : '操作失败');
        } finally {
            setBusy(false);
        }
    }

    /** Opens only the backend-issued Langfuse URL and preserves local evidence on failure. */
    async function openTrace() {
        if (!selected?.agent_run_id) {
            setTraceNotice('本地证据可用，远端 Trace 不可用：当前运行尚未关联 AgentRun。');
            return;
        }
        try {
            const result = await evaluationApi.traceLink(selected.agent_run_id);
            if (!result.available || !result.url) {
                setTraceNotice(`本地证据可用，远端 Trace 不可用：${result.message ?? 'Langfuse Trace 暂不可用'}。`);
                return;
            }
            setTraceNotice(null);
            window.open(result.url, '_blank', 'noopener,noreferrer');
        } catch (error) {
            const message = error instanceof Error ? error.message : '打开 Trace 失败';
            setTraceNotice(`本地证据可用，远端 Trace 不可用：${message}。`);
        }
    }

    async function createCandidateDataset() {
        if (!caseDetail) return;
        try {
            const expected = caseDetail.case.expected ?? {};
            await evaluationApi.createCandidateDataset(caseDetail.id, {
                name: candidateName,
                version: candidateVersion,
                case_key: `${caseDetail.case.case_key}-regression`,
                category: 'regression',
                expected_output: expected.expected_output ?? null,
                expected_facts: expected.expected_facts ?? [],
                forbidden_claims: expected.forbidden_claims ?? [],
                tags: [...new Set([...(caseDetail.case.tags ?? []), 'candidate', 'regression'])],
                severity: caseDetail.case.severity,
            });
            toast.success('已创建失败案例候选 Dataset Version');
            await onRefresh();
        } catch (error) {
            toast.error(error instanceof Error ? error.message : '沉淀回归案例失败');
        }
    }

    function toggleDatasetCase(caseId: string, checked: boolean) {
        setSelectedCaseIds((current) => {
            const next = new Set(current);
            if (checked) next.add(caseId); else next.delete(caseId);
            return next;
        });
    }

    return <div className="space-y-4">
        <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center justify-between"><div><h3 className="font-semibold">新建评测</h3><p className="mt-1 text-xs text-slate-500">选择真实 Agent、Prompt/基线、模型、Dataset、重复次数、Judge、人工抽检和预算。</p></div><Play className="h-4 w-4 text-teal-700" /></div>
            <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Field label="评测套件"><select className="h-10 w-full rounded-md border px-3 text-sm" value={effectiveSuiteId} onChange={(event) => setForm({ ...form, suite_id: event.target.value })}><option value="">选择套件</option>{suites.map((suite) => <option key={suite.id} value={suite.id}>{suite.name} · {suite.agent_name}</option>)}</select></Field>
                <Field label="模型配置哈希"><Input value={form.model_config_hash} onChange={(event) => setForm({ ...form, model_config_hash: event.target.value })} placeholder="sha256:..." /></Field>
                <Field label="Prompt 名称"><Input value={form.prompt_name} onChange={(event) => setForm({ ...form, prompt_name: event.target.value })} placeholder="可选" /></Field>
                <Field label="Prompt 版本"><Input value={form.prompt_version} onChange={(event) => setForm({ ...form, prompt_version: event.target.value })} placeholder="可选" /></Field>
                <Field label="基线运行"><select className="h-10 w-full rounded-md border px-3 text-sm" value={form.baseline_run_id} onChange={(event) => setForm({ ...form, baseline_run_id: event.target.value })}><option value="">不比较基线</option><option value="__production__">自动选择 Production 基线</option>{runs.filter((run) => run.status === 'succeeded' && run.id !== selectedRunId).map((run) => <option key={run.id} value={run.id}>{run.agent_name} · Prompt {run.prompt_version ?? '-'} · {run.id.slice(-8)}</option>)}</select></Field>
                <Field label="重复次数"><Input type="number" min="1" max="10" value={form.repetition_count} onChange={(event) => setForm({ ...form, repetition_count: event.target.value })} /></Field>
                <Field label="最大并发"><Input type="number" min="1" max="10" value={form.max_concurrency} onChange={(event) => setForm({ ...form, max_concurrency: event.target.value })} /></Field>
                <Field label="预算 USD"><Input type="number" min="0.01" max="1000" step="0.01" value={form.max_budget_usd} onChange={(event) => setForm({ ...form, max_budget_usd: event.target.value })} /></Field>
                <Field label="人工抽检比例 %"><Input type="number" min="0" max="100" step="1" value={form.human_review_rate} onChange={(event) => setForm({ ...form, human_review_rate: event.target.value })} /></Field>
                <label className="flex h-10 items-center gap-2 self-end rounded-md border px-3 text-sm"><Checkbox checked={form.include_judges} onCheckedChange={(checked) => setForm({ ...form, include_judges: checked })} />启用 LLM Judge</label>
            </div>
            {visibleDataset && <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50/70 p-3"><div className="flex flex-wrap items-center justify-between gap-2"><div><div className="text-sm font-medium">只运行选中案例（可选）</div><div className="text-xs text-slate-500">{visibleDataset.name} · {visibleDataset.version} · {visibleDataset.case_count} cases；未选择时运行全部案例。</div></div><div className="flex gap-2"><Button size="sm" variant="ghost" onClick={() => setSelectedCaseIds(new Set(visibleDataset.cases.map((item) => item.id)))}>全选</Button><Button size="sm" variant="ghost" onClick={() => setSelectedCaseIds(new Set())}>清空</Button></div></div><div className="mt-3 grid max-h-44 gap-2 overflow-auto sm:grid-cols-2 lg:grid-cols-3">{visibleDataset.cases.map((item) => <label key={item.id} className="flex items-start gap-2 rounded-lg border bg-white p-2 text-xs"><Checkbox checked={selectedCaseIds.has(item.id)} onCheckedChange={(checked) => toggleDatasetCase(item.id, checked)} /><span><span className="font-medium text-slate-800">{item.case_key}</span><span className="block text-slate-500">{item.category} · {item.severity}</span></span></label>)}</div></div>}
            <Button className="mt-4" onClick={() => void createRun()} disabled={busy}>{busy ? <Loader2 className="animate-spin" /> : <Play />}运行真实 Agent{selectedCaseIds.size ? `（${selectedCaseIds.size} 个案例）` : ''}</Button>
        </section>

        <div className="grid gap-4 xl:grid-cols-[380px_minmax(0,1fr)]">
            <section className="rounded-2xl border bg-white p-3 shadow-sm">
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2 px-1"><h3 className="font-semibold">评测运行</h3><div className="flex items-center gap-2"><select className="h-8 rounded-md border px-2 text-xs" value={caseFilterKey(caseFilters)} onChange={(event) => setCaseFilters((current) => applyCasePreset(current, event.target.value))} aria-label="案例筛选"><option value="all">全部案例</option><option value="failed">失败案例</option><option value="review">待人工复核</option><option value="gate_failed">硬门禁失败</option></select><Button variant="ghost" size="icon-sm" onClick={() => void onRefresh()} aria-label="刷新评测运行"><RefreshCw /></Button></div></div>
                <div className="mb-3 grid gap-2 rounded-xl border bg-slate-50 p-2 sm:grid-cols-2">
                    <Input className="h-8 text-xs" value={caseFilters.tool_name ?? ''} onChange={(event) => setCaseFilters((current) => ({ ...current, tool_name: event.target.value || undefined }))} placeholder="Tool name" aria-label="按工具名筛选" />
                    <Input className="h-8 text-xs" value={caseFilters.error_category ?? ''} onChange={(event) => setCaseFilters((current) => ({ ...current, error_category: event.target.value || undefined }))} placeholder="Error category" aria-label="按错误分类筛选" />
                    <CaseFilterSelect label="Tool effect" value={caseFilters.tool_effect} onChange={(value) => setCaseFilters((current) => ({ ...current, tool_effect: value as EvaluationToolEffect | undefined }))} options={[['read', 'read'], ['write', 'write'], ['external', 'external'], ['none', 'none']]} />
                    <CaseFilterSelect label="Tool status" value={caseFilters.tool_status} onChange={(value) => setCaseFilters((current) => ({ ...current, tool_status: value }))} options={[['completed', 'completed'], ['failed', 'failed'], ['blocked', 'blocked'], ['started', 'started'], ['skipped', 'skipped']]} />
                    <CaseFilterSelect label="Approval" value={caseFilters.approval_status} onChange={(value) => setCaseFilters((current) => ({ ...current, approval_status: value as EvaluationApprovalStatus | undefined }))} options={[['approved', 'approved'], ['pending', 'pending'], ['rejected', 'rejected'], ['not_required', 'not required']]} />
                    <CaseFilterSelect label="External side effect" value={optionalBooleanValue(caseFilters.has_external_side_effect)} onChange={(value) => setCaseFilters((current) => ({ ...current, has_external_side_effect: parseOptionalBoolean(value) }))} options={[['true', '有 external'], ['false', '无 external']]} />
                    <CaseFilterSelect label="Trace" value={optionalBooleanValue(caseFilters.trace_incomplete)} onChange={(value) => setCaseFilters((current) => ({ ...current, trace_incomplete: parseOptionalBoolean(value) }))} options={[['true', 'Trace incomplete'], ['false', 'Trace complete']]} />
                    <CaseFilterSelect label="Retrieval" value={optionalBooleanValue(caseFilters.retrieval_empty)} onChange={(value) => setCaseFilters((current) => ({ ...current, retrieval_empty: parseOptionalBoolean(value) }))} options={[['true', '空召回'], ['false', '非空召回']]} />
                    <Button className="sm:col-span-2" size="sm" variant="ghost" onClick={() => setCaseFilters({})}>清空全部筛选</Button>
                </div>
                <div className="max-h-[760px] space-y-2 overflow-auto">{runs.map((run) => <button key={run.id} onClick={() => void loadCases(run.id, caseFilters)} className={`w-full rounded-xl border p-3 text-left transition ${selectedRunId === run.id ? 'border-teal-500 bg-teal-50' : 'hover:bg-slate-50'}`}><div className="flex justify-between gap-2"><span className="font-medium">{run.agent_name} · {run.prompt_name ?? '默认 Prompt'}</span><Status status={run.status} /></div><div className="mt-1 text-xs text-slate-500">{run.dataset_version} · Prompt {run.prompt_version ?? '-'} · 重复 {run.repetition_count}</div><div className="mt-1 text-[11px] text-slate-400">{shortHash(run.model_config_hash)} · {formatDate(run.created_at)}</div><div className="mt-2 h-1.5 rounded-full bg-slate-100"><div className="h-full rounded-full bg-teal-600" style={{ width: `${runProgress(run) * 100}%` }} /></div><div className="mt-2 flex justify-between text-[11px] text-slate-500"><span>完全成功 {formatRate(run.summary.complete_success_rate)}</span><span>硬门禁 {String(run.summary.hard_gate_failure_count ?? 0)}</span><span>人工 {String(run.summary.needs_review_count ?? 0)}</span></div></button>)}{!runs.length && <Empty text="暂无评测运行。" />}</div>
            </section>

            <section className="min-w-0 rounded-2xl border bg-white p-4 shadow-sm">
                <div className="flex flex-wrap items-center justify-between gap-2"><div><h3 className="font-semibold">运行详情</h3><p className="text-xs text-slate-500">确定性规则、Judge、人工标注和用户反馈保持来源分离。</p></div>{selected && <div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" onClick={() => void downloadEvaluationReport(selected.id)}><Download />HTML 报告</Button><Button size="sm" variant="outline" onClick={() => void openTrace()}><ExternalLink />Langfuse</Button><Button size="sm" variant="outline" onClick={() => void action('review')}><UserCheck />发起复核</Button><Button size="sm" variant="outline" onClick={() => void action('retry')}><RotateCcw />重试失败</Button><Button size="sm" variant="outline" onClick={() => void action('cancel')}><Square />取消</Button></div>}</div>
                {selected && (traceNotice || !selected.agent_run_id) && <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">{traceNotice ?? '本地证据可用，远端 Trace 不可用：当前运行尚未关联 AgentRun。'}</div>}
                {selected && <><div className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4 xl:grid-cols-6"><Info label="状态" value={selected.status} /><Info label="案例" value={String(selected.summary.case_total ?? 0)} /><Info label="完成" value={String(selected.summary.completed_count ?? 0)} /><Info label="失败" value={String(selected.summary.failed_count ?? 0)} /><Info label="完全成功" value={formatRate(selected.summary.complete_success_rate)} /><Info label="硬门禁" value={String(selected.summary.hard_gate_failure_count ?? 0)} /><Info label="P95 延迟" value={`${formatNumber(selected.summary.p95_latency_ms)} ms`} /><Info label="Token" value={formatNumber(selected.summary.token_total)} /><Info label="Trace 完整率" value={formatRate(selected.summary.trace_completeness_rate)} /><Info label="语义已评测率" value={formatRate(selected.summary.semantic_evaluated_rate)} /><Info label="Tool / 失败" value={`${formatNumber(selected.summary.tool_call_total)} / ${formatNumber(selected.summary.tool_call_failed_count)}`} /><Info label="Tool 阻断率" value={formatRate(selected.summary.tool_blocked_rate)} /><Info label="Tool 重试率" value={formatRate(selected.summary.tool_retry_rate)} /><Info label="External / 阻断" value={`${formatNumber(selected.summary.external_effect_total)} / ${formatNumber(selected.summary.external_effect_blocked_count)}`} /><Info label="审批违规" value={formatNumber(selected.summary.approval_violation_count)} /><Info label="检索成功率" value={formatRate(selected.summary.retrieval_success_rate)} /><Info label="检索空召回率" value={formatRate(selected.summary.retrieval_empty_rate)} /><Info label="检索采用率" value={formatRate(selected.summary.retrieval_adopted_rate)} /><Info label="依赖失败率" value={formatRate(selected.summary.dependency_failure_rate)} /><Info label="Langfuse 上报" value={formatNumber(selected.summary.langfuse_reported_case_count)} /><Info label="Langfuse 降级" value={formatNumber(selected.summary.langfuse_failed_case_count)} /></div><Baseline summary={selected.summary} /></>}
                <div className="mt-4 overflow-auto"><table className="w-full min-w-[760px] text-left text-sm"><thead className="text-xs text-slate-500"><tr><th className="py-2">案例</th><th>重复</th><th>状态</th><th>完全成功</th><th>硬门禁</th><th>语义分数</th><th>人工队列</th><th>延迟</th></tr></thead><tbody>{cases.map((item) => <tr key={item.id} onClick={() => void loadCaseDetail(item.id)} className={`cursor-pointer border-t hover:bg-slate-50 ${selectedCaseRunId === item.id ? 'bg-teal-50/70' : ''}`}><td className="py-3 font-mono text-xs">{item.case_id}</td><td>{item.repetition_index + 1}</td><td>{item.status}</td><td>{item.complete_success == null ? "-" : item.complete_success ? "是" : "否"}</td><td className={item.hard_gate_passed ? 'text-emerald-700' : 'text-red-700'}>{item.hard_gate_passed ? '通过' : '失败'}</td><td>{item.overall_score == null ? '-' : item.overall_score.toFixed(3)}</td><td>{item.needs_review ? '待复核' : '-'}</td><td>{item.latency_ms} ms</td></tr>)}</tbody></table></div>
                {!selected && <Empty text="选择一个运行查看案例。" />}

                {detailBusy && <div className="mt-5 flex items-center justify-center rounded-xl border border-dashed p-10 text-sm text-slate-500"><Loader2 className="mr-2 animate-spin" />加载案例详情…</div>}
                {caseDetail && !detailBusy && <EvaluationCaseDetail key={caseDetail.id} detail={caseDetail} candidateName={candidateName} candidateVersion={candidateVersion} onCandidateName={setCandidateName} onCandidateVersion={setCandidateVersion} onCreateCandidate={createCandidateDataset} />}
            </section>
        </div>
    </div>;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) { return <label className="grid gap-1 text-xs font-medium text-slate-600"><span>{label}</span>{children}</label>; }
function Info({ label, value }: { label: string; value: string }) { return <div className="rounded-xl bg-slate-50 p-3"><div className="text-xs text-slate-500">{label}</div><div className="mt-1 truncate font-semibold" title={value}>{value}</div></div>; }
function Status({ status }: { status: string }) { const tone = status === 'succeeded' ? 'bg-emerald-50 text-emerald-700' : status === 'failed' ? 'bg-red-50 text-red-700' : status === 'cancelled' ? 'bg-slate-100 text-slate-600' : 'bg-blue-50 text-blue-700'; return <span className={`rounded-full px-2 py-0.5 text-[10px] uppercase ${tone}`}>{status}</span>; }
function Empty({ text }: { text: string }) { return <div className="my-3 rounded-xl border border-dashed p-6 text-center text-sm text-slate-500">{text}</div>; }
function Baseline({ summary }: { summary: Record<string, unknown> }) { const comparison = summary.baseline_comparison as Record<string, unknown> | undefined; if (!comparison) return null; return <div className="mt-3 rounded-xl border border-blue-100 bg-blue-50/60 p-3 text-xs text-blue-900"><div className="font-medium">与基线运行比较</div><div className="mt-2 flex flex-wrap gap-2"><Delta label="完全成功率" value={comparison.complete_success_rate_delta} percent /><Delta label="P95 延迟" value={comparison.p95_latency_ms_delta} suffix=" ms" /><Delta label="Token" value={comparison.token_total_delta_percent} percent /></div></div>; }
function Delta({ label, value, percent = false, suffix = '' }: { label: string; value: unknown; percent?: boolean; suffix?: string }) { const number = Number(value); const text = value == null || !Number.isFinite(number) ? '-' : `${number > 0 ? '+' : ''}${(percent ? number * 100 : number).toFixed(1)}${percent ? '%' : suffix}`; return <span className="rounded-md bg-white px-2 py-1">{label} {text}</span>; }
function promptCandidateForm(): RunForm { let candidate: { name?: string; version?: number; compareProduction?: boolean } = {}; if (typeof window !== 'undefined') { try { candidate = JSON.parse(localStorage.getItem('evaluationPromptCandidate') || '{}'); } catch { candidate = {}; } } return { suite_id: '', model_config_hash: 'sha256:default', prompt_name: candidate.name ?? '', prompt_version: candidate.version == null ? '' : String(candidate.version), baseline_run_id: candidate.compareProduction ? '__production__' : '', repetition_count: '1', max_concurrency: '2', max_budget_usd: '5', human_review_rate: '10', include_judges: false }; }
function caseFilterKey(filters: EvaluationCaseRunFilters): string {
    if (filters.status === 'failed') return 'failed';
    if (filters.needs_review === true) return 'review';
    if (filters.hard_gate_passed === false) return 'gate_failed';
    return 'all';
}

function parseCaseFilter(value: string): EvaluationCaseRunFilters {
    if (value === 'failed') return { status: 'failed' };
    if (value === 'review') return { needs_review: true };
    if (value === 'gate_failed') return { hard_gate_passed: false };
    return {};
}

/** Applies one preset without discarding advanced owner-scoped filters. */
function applyCasePreset(filters: EvaluationCaseRunFilters, value: string): EvaluationCaseRunFilters {
    const advanced = { ...filters };
    delete advanced.status;
    delete advanced.needs_review;
    delete advanced.hard_gate_passed;
    return { ...advanced, ...parseCaseFilter(value) };
}

/** Renders one compact optional selector used by server-side case filtering. */
function CaseFilterSelect({ label, value, options, onChange }: { label: string; value?: string; options: Array<[string, string]>; onChange: (value: string | undefined) => void }) {
    return <select className="h-8 rounded-md border bg-white px-2 text-xs" value={value ?? ''} onChange={(event) => onChange(event.target.value || undefined)} aria-label={label}><option value="">{label}: 全部</option>{options.map(([option, text]) => <option key={option} value={option}>{text}</option>)}</select>;
}

/** Converts tri-state boolean filters to a stable select value. */
function optionalBooleanValue(value: boolean | undefined): string | undefined {
    return value == null ? undefined : String(value);
}

/** Parses a tri-state select without treating “all” as false. */
function parseOptionalBoolean(value: string | undefined): boolean | undefined {
    return value == null ? undefined : value === 'true';
}

function formatRate(value: unknown): string { const number = Number(value); return value == null || !Number.isFinite(number) ? '-' : `${(number * 100).toFixed(1)}%`; }
function formatNumber(value: unknown): string { const number = Number(value); return value == null || !Number.isFinite(number) ? '-' : Math.round(number).toLocaleString('zh-CN'); }
function formatDate(value: string): string { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN'); }
function shortHash(value: string): string { return value.length > 20 ? `${value.slice(0, 10)}…${value.slice(-7)}` : value; }
