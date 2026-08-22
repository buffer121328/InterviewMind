'use client';

import { useEffect, useRef, useState } from 'react';
import { CheckCircle2, GitCompareArrows, LockKeyhole, ShieldAlert, UserCheck } from 'lucide-react';
import { CartesianGrid, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from 'recharts';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { ContextualHelpIcon } from '@/components/ContextualHelpIcon';
import { PaginationControls } from '@/components/PaginationControls';
import {
    evaluationApi,
    type EvaluationAnnotation,
    type EvaluationCalibration,
    type EvaluationCaseRun,
    type EvaluationCaseRunDetail,
    type EvaluationDataset,
    type EvaluationGatePolicy,
    type EvaluationRun,
    type EvaluationSuite,
} from '@/lib/api/evaluations';
import { deriveAnnotationState } from '@/lib/evaluationAnnotations';
import { buildEvaluationReviewGuidance } from '@/lib/evaluationCaseDetail';
import { getTotalPages } from '@/lib/pagination';
import { toast } from 'sonner';

const MANAGEMENT_LIST_PAGE_SIZE = 10;

export function DatasetsPanel({ datasets, suites, focusDatasetId, onRefresh }: { datasets: EvaluationDataset[]; suites: EvaluationSuite[]; focusDatasetId?: string | null; onRefresh: () => Promise<void> }) {
    const [datasetJson, setDatasetJson] = useState(JSON.stringify({ name: 'interview-regression', version: 'v1', source: 'manual', cases: [{ case_key: 'case-001', category: 'interview', input: { session_id: 'fixture-session' }, expected_facts: ['asks one question'], forbidden_claims: ['fabricated experience'], tags: ['smoke'], severity: 'high' }] }, null, 2));
    const [suite, setSuite] = useState({ name: '', agent_name: '', dataset_version_id: '', rubric_version: 'v1' });
    const [datasetPage, setDatasetPage] = useState(1);
    const [suitePage, setSuitePage] = useState(1);
    const focusedRef = useRef<HTMLDivElement | null>(null);
    const effectiveDatasetVersionId = suite.dataset_version_id || datasets[0]?.id || '';
    const datasetPageCount = getTotalPages(datasets.length, MANAGEMENT_LIST_PAGE_SIZE);
    const suitePageCount = getTotalPages(suites.length, MANAGEMENT_LIST_PAGE_SIZE);
    const visibleDatasets = datasets.slice(
        (datasetPage - 1) * MANAGEMENT_LIST_PAGE_SIZE,
        datasetPage * MANAGEMENT_LIST_PAGE_SIZE,
    );
    const visibleSuites = suites.slice(
        (suitePage - 1) * MANAGEMENT_LIST_PAGE_SIZE,
        suitePage * MANAGEMENT_LIST_PAGE_SIZE,
    );

    useEffect(() => {
        const index = datasets.findIndex((item) => item.id === focusDatasetId);
        if (index >= 0) setDatasetPage(Math.floor(index / MANAGEMENT_LIST_PAGE_SIZE) + 1);
    }, [focusDatasetId, datasets]);

    useEffect(() => {
        setDatasetPage((page) => Math.min(page, datasetPageCount));
    }, [datasetPageCount]);

    useEffect(() => {
        setSuitePage((page) => Math.min(page, suitePageCount));
    }, [suitePageCount]);

    useEffect(() => {
        if (!focusDatasetId || !focusedRef.current) return;
        focusedRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, [focusDatasetId, visibleDatasets]);

    async function createDataset() {
        try {
            await evaluationApi.createDataset(JSON.parse(datasetJson));
            toast.success('Dataset Version 已创建；完成校准并锁定后方可运行');
            await onRefresh();
        } catch (error) { toast.error(error instanceof Error ? error.message : '创建失败'); }
    }
    async function createSuite() {
        try {
            await evaluationApi.createSuite({ ...suite, dataset_version_id: effectiveDatasetVersionId });
            toast.success('评测套件已创建');
            await onRefresh();
        } catch (error) { toast.error(error instanceof Error ? error.message : '创建失败'); }
    }
    async function updateStatus(item: EvaluationDataset, action: 'annotating' | 'calibrated' | 'locked' | 'retired') {
        try {
            if (action === 'locked') await evaluationApi.lockDataset(item.id);
            else await evaluationApi.updateDatasetStatus(item.id, action);
            toast.success(`Dataset 已推进为 ${action}`);
            await onRefresh();
        } catch (error) { toast.error(error instanceof Error ? error.message : '状态更新失败'); }
    }

    return <div className="grid gap-4 xl:grid-cols-[1.1fr_1fr]">
        <section className="rounded-2xl border bg-white p-4 shadow-sm"><div className="flex items-center justify-between"><div><h3 className="font-semibold">Dataset Versions</h3><p className="mt-1 text-xs text-slate-500">draft → annotating → calibrated → locked；锁定版本不可原地改写。</p></div><LockKeyhole className="h-4 w-4 text-teal-700" /></div><div className="mt-3 space-y-2">{visibleDatasets.map((item) => <div key={item.id} ref={item.id === focusDatasetId ? focusedRef : undefined} className={`rounded-xl border p-3 ${item.id === focusDatasetId ? 'border-teal-500 bg-teal-50 ring-2 ring-teal-200' : ''}`}><div className="flex flex-wrap items-start justify-between gap-3"><div><div className="font-medium">{item.name} · {item.version}</div><div className="mt-1 text-xs text-slate-500">{item.case_count} cases · {item.source} · hash {shortHash(item.content_hash)}</div><span className={`mt-2 inline-flex rounded-full px-2 py-0.5 text-[10px] uppercase ${datasetTone(item.status)}`}>{item.status}</span></div><div className="flex flex-wrap gap-2">{item.status === 'draft' && <Button size="sm" variant="outline" onClick={() => void updateStatus(item, 'annotating')}>开始标注</Button>}{['draft', 'annotating'].includes(item.status) && <Button size="sm" variant="outline" onClick={() => void updateStatus(item, 'calibrated')}>标记 calibrated</Button>}{item.status === 'calibrated' && <Button size="sm" onClick={() => void updateStatus(item, 'locked')}><LockKeyhole />锁定版本</Button>}{item.status !== 'retired' && <Button size="sm" variant="ghost" onClick={() => void updateStatus(item, 'retired')}>退役</Button>}</div></div></div>)}{datasets.length === 0 && <Empty text="暂无 Dataset Version。" />}</div>{datasets.length > MANAGEMENT_LIST_PAGE_SIZE && <PaginationControls className="mt-4" page={datasetPage} total={datasets.length} pageSize={MANAGEMENT_LIST_PAGE_SIZE} onPageChange={setDatasetPage} />}<div className="mt-5 border-t pt-4"><h4 className="text-sm font-semibold">创建加密 Dataset Version</h4><p className="mt-1 text-xs text-slate-500">输入与 Golden 由后端加密；列表仅返回摘要。</p><Textarea className="mt-3 min-h-64 font-mono text-xs" value={datasetJson} onChange={(event) => setDatasetJson(event.target.value)} /><Button className="mt-3" onClick={() => void createDataset()}>创建新版本</Button></div></section>
        <section className="rounded-2xl border bg-white p-4 shadow-sm"><h3 className="font-semibold">Evaluation Suites</h3><div className="mt-3 space-y-2">{visibleSuites.map((item) => <div key={item.id} className="rounded-xl border p-3"><div className="font-medium">{item.name}</div><div className="mt-1 text-xs text-slate-500">{item.agent_name} · Rubric {item.rubric_version}</div><div className="mt-1 font-mono text-[10px] text-slate-400">Dataset {item.dataset_version_id}</div></div>)}{suites.length === 0 && <Empty text="暂无 Evaluation Suite。" />}</div>{suites.length > MANAGEMENT_LIST_PAGE_SIZE && <PaginationControls className="mt-4" page={suitePage} total={suites.length} pageSize={MANAGEMENT_LIST_PAGE_SIZE} onPageChange={setSuitePage} />}<div className="mt-5 grid gap-3 border-t pt-4"><Input placeholder="套件名称" value={suite.name} onChange={(event) => setSuite({ ...suite, name: event.target.value })} /><Input placeholder="生产 Agent allowlist 名称" value={suite.agent_name} onChange={(event) => setSuite({ ...suite, agent_name: event.target.value })} /><select className="h-10 rounded-md border px-3 text-sm" value={effectiveDatasetVersionId} onChange={(event) => setSuite({ ...suite, dataset_version_id: event.target.value })}><option value="">选择 Dataset Version</option>{datasets.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.version} · {item.status}</option>)}</select><Input placeholder="Rubric 版本" value={suite.rubric_version} onChange={(event) => setSuite({ ...suite, rubric_version: event.target.value })} /><Button onClick={() => void createSuite()}>创建套件</Button></div></section>
    </div>;
}

type AnnotationType = 'binary' | 'scalar' | 'categorical' | 'pairwise' | 'evidence';

export function AnnotationsPanel({ queue, onRefresh }: { queue: Array<EvaluationCaseRun & { agent_name: string }>; onRefresh: () => Promise<void> }) {
    const [selected, setSelected] = useState<string | null>(null);
    const [items, setItems] = useState<EvaluationAnnotation[]>([]);
    const [detail, setDetail] = useState<EvaluationCaseRunDetail | null>(null);
    const [annotationType, setAnnotationType] = useState<AnnotationType>('binary');
    const [metric, setMetric] = useState('quality.overall');
    const [customMetric, setCustomMetric] = useState('quality.custom');
    const reviewer = 'owner-expert';
    const [rubricVersion, setRubricVersion] = useState('v1');
    const [value, setValue] = useState('true');
    const [labels, setLabels] = useState('');
    const [comment, setComment] = useState('');
    const [confidence, setConfidence] = useState('1');
    const [resolutionStatus, setResolutionStatus] = useState('approved');
    const [resolutionNote, setResolutionNote] = useState('');
    const [evidenceStart, setEvidenceStart] = useState('0');
    const [evidenceEnd, setEvidenceEnd] = useState('1');
    const [evidenceText, setEvidenceText] = useState('');
    const state = deriveAnnotationState(items);
    const reviewGuidance = detail ? buildEvaluationReviewGuidance(detail) : null;

    async function load(id: string) {
        setSelected(id);
        try {
            const [annotationResult, detailResult] = await Promise.all([evaluationApi.annotations(id), evaluationApi.caseRun(id)]);
            setItems(annotationResult.items);
            setDetail(detailResult);
        } catch (error) { toast.error(error instanceof Error ? error.message : '加载失败'); }
    }
    function parsedValue(): unknown {
        if (annotationType === 'binary') return value === 'true';
        if (annotationType === 'scalar') return Number(value);
        if (annotationType === 'pairwise') return { winner: value };
        if (annotationType === 'categorical') return value;
        return { supported: value === 'supported' };
    }
    async function add() {
        if (!selected) return;
        const spans = annotationType === 'evidence' && evidenceText ? [{ start: Number(evidenceStart), end: Number(evidenceEnd), text: evidenceText }] : [];
        try {
            await evaluationApi.addAnnotation(selected, {
                rubric_version: rubricVersion,
                annotation_type: annotationType,
                metric_name: metric === 'custom' ? customMetric : metric,
                value: parsedValue(),
                reviewer_key: reviewer,
                blind: false,
                labels: labels.split(',').map((item) => item.trim()).filter(Boolean),
                evidence_spans: spans,
                comment: comment || null,
                confidence: Number(confidence),
            });
            await load(selected);
            toast.success('已追加标注 revision');
            await onRefresh();
        } catch (error) { toast.error(error instanceof Error ? error.message : '标注失败'); }
    }
    async function resolveReview() {
        if (!selected || !resolutionNote.trim()) return toast.error('请填写处理说明');
        try {
            await evaluationApi.resolveReview(selected, { status: resolutionStatus, reviewer_key: reviewer, comment: resolutionNote.trim() });
            toast.success('人工处理结论已保存');
            setResolutionNote('');
            await onRefresh();
        } catch (error) { toast.error(error instanceof Error ? error.message : '保存处理结论失败'); }
    }

    return <div className="grid gap-4 xl:grid-cols-[340px_minmax(0,1fr)]">
        <section className="rounded-2xl border bg-white p-4 shadow-sm"><div className="flex items-center justify-between"><div><h3 className="font-semibold">人工复核队列</h3><p className="mt-1 text-xs text-slate-500">失败、硬门禁、低置信度与抽检案例。</p></div><UserCheck className="h-4 w-4 text-teal-700" /></div><div className="mt-3 max-h-[760px] space-y-2 overflow-auto">{queue.map((item) => <button key={item.id} onClick={() => void load(item.id)} className={`w-full rounded-xl border p-3 text-left ${selected === item.id ? 'border-teal-500 bg-teal-50' : 'hover:bg-slate-50'}`}><div className="flex justify-between"><span className="font-medium">{item.agent_name}</span><span className="text-[10px] text-amber-700">待人工复核</span></div><div className="mt-1 font-mono text-[11px] text-slate-500">{item.case_id}</div><div className="mt-1 text-xs text-slate-500">{item.error_category ?? (item.hard_gate_passed ? '抽样/低置信度' : '硬门禁失败')}</div></button>)}{queue.length === 0 && <Empty text="暂无待复核案例。" />}</div></section>
        <section className="min-w-0 rounded-2xl border bg-white p-4 shadow-sm"><div className="flex flex-wrap justify-between gap-2"><div><h3 className="font-semibold">专家人工复核</h3><p className="mt-1 text-xs text-slate-500">当前为个人项目，所有新标注由本人专家直接记录；历史 revision 仍保留。</p></div><div className="flex items-center gap-2"><ContextualHelpIcon id="evaluation-review-form" label="怎么填"><span>先选择指标，再选择中文结果。评论只写判断依据，不要粘贴密钥、Cookie 或完整业务隐私。</span></ContextualHelpIcon><span className={`h-fit rounded-full px-3 py-1 text-xs ${annotationStateTone(state)}`}>{state === 'pending' ? '待填写' : '已填写'}</span></div></div>
            {detail ? <>{reviewGuidance && <section className="mt-4 min-w-0 rounded-xl border border-amber-200 bg-amber-50/60 p-3"><div className="break-words text-sm font-semibold text-amber-950">{reviewGuidance.title}</div><p className="mt-1 break-words text-xs leading-5 text-amber-900">先看下面的简明结论卡；标签说明是否纳入治理以及由系统自动检查还是需要人工确认；只有结论与实际判断不一致时，才展开原始 JSON 追查。</p><div className="mt-3 grid min-w-0 gap-2 sm:grid-cols-2">{reviewGuidance.checks.map((check) => <div key={check.label} className={`min-w-0 rounded-lg border bg-white p-2.5 text-xs ${check.outcome === 'failed' ? 'border-red-200 text-red-900' : check.outcome === 'passed' ? 'border-emerald-200 text-emerald-900' : 'border-amber-200 text-amber-900'}`}><div className="flex flex-wrap items-start justify-between gap-2"><ReviewCheckHeading label={check.label} /><div className="flex shrink-0 flex-wrap justify-end gap-1"><span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${check.scopeLabel === '纳入治理' ? 'bg-blue-50 text-blue-800' : 'bg-slate-100 text-slate-600'}`}>{check.scopeLabel}</span><span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-600">{check.actionLabel}</span></div></div><div className="mt-2 whitespace-pre-line break-words leading-5">{check.detail}</div></div>)}</div><p className="mt-3 whitespace-pre-line break-words text-xs leading-5 text-amber-950">{reviewGuidance.recommendation}</p></section>}<details className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-3"><summary className="cursor-pointer break-words text-sm font-medium text-slate-700">需要追查时再展开原始 JSON</summary><p className="mt-1 text-xs leading-5 text-slate-500">原始数据只用于复核结论存在争议的情况，正常审核不需要阅读。</p><div className="mt-3 grid gap-3 lg:grid-cols-2"><JsonPreview title="案例输入 / 证据" value={{ input: detail.case.input, expected: detail.case.expected }} /><JsonPreview title="待评输出" value={detail.actual_output} /></div>{annotationType === 'pairwise' && <div className="mt-3 grid gap-3 lg:grid-cols-2"><JsonPreview title="盲化输出 A" value={detail.pairwise_outputs.A} /><JsonPreview title="盲化输出 B" value={detail.pairwise_outputs.B ?? '当前运行未关联可用基线'} /></div>}</details></> : <Empty text="从左侧选择一个案例。" />}
            <div className="mt-4 grid gap-3 border-t pt-4 sm:grid-cols-2 lg:grid-cols-4"><Field label="标注类型"><select className="h-10 rounded-md border px-3 text-sm" value={annotationType} onChange={(event) => { const type = event.target.value as AnnotationType; setAnnotationType(type); setValue(defaultAnnotationValue(type)); }}><option value="binary">是否通过</option><option value="scalar">质量分数</option><option value="categorical">问题分类</option><option value="pairwise">两份输出比较</option><option value="evidence">证据关系</option></select></Field><Field label="评估指标"><select className="h-10 rounded-md border px-3 text-sm" value={metric} onChange={(event) => setMetric(event.target.value)}><option value="quality.overall">整体质量</option><option value="factual.expected_fact_coverage">期望事实覆盖</option><option value="quality.semantic">语义质量</option><option value="trace.completeness">Trace 完整性</option><option value="rubric.expected_output_value_coverage">期望输出覆盖</option><option value="custom">其他指标（需手动填写）</option></select></Field>{metric === 'custom' && <Field label="指标名称"><Input value={customMetric} onChange={(event) => setCustomMetric(event.target.value)} placeholder="例如 quality.conciseness" /></Field>}<Field label="Rubric 版本"><Input value={rubricVersion} onChange={(event) => setRubricVersion(event.target.value)} /></Field><AnnotationValue type={annotationType} value={value} onChange={setValue} /><Field label="置信度 0-1"><Input type="number" min="0" max="1" step="0.05" value={confidence} onChange={(event) => setConfidence(event.target.value)} /></Field><Field label="问题标签"><select className="h-10 rounded-md border px-3 text-sm" value={labels} onChange={(event) => setLabels(event.target.value)}><option value="">无特殊标签</option><option value="factual_hallucination">事实虚构</option><option value="factual_omission">事实遗漏</option><option value="trace_incomplete">Trace 不完整</option><option value="dependency_failure">依赖失败</option><option value="other">其他</option></select></Field></div>
            {annotationType === 'evidence' && <div className="mt-3 grid gap-3 sm:grid-cols-[120px_120px_1fr]"><Field label="开始位置"><Input type="number" min="0" value={evidenceStart} onChange={(event) => setEvidenceStart(event.target.value)} /></Field><Field label="结束位置"><Input type="number" min="1" value={evidenceEnd} onChange={(event) => setEvidenceEnd(event.target.value)} /></Field><Field label="证据文本"><Input value={evidenceText} onChange={(event) => setEvidenceText(event.target.value)} placeholder="仅填写业务证据，不得粘贴认证材料" /></Field></div>}
            <Textarea className="mt-3" value={comment} onChange={(event) => setComment(event.target.value)} placeholder="判断依据（必填时建议写清楚证据和结论）" /><div className="mt-3 flex flex-wrap gap-2"><Button onClick={() => void add()} disabled={!selected}><CheckCircle2 />保存专家标注</Button></div><div className="mt-4 rounded-xl border border-teal-100 bg-teal-50/50 p-3"><div className="flex items-center gap-2 text-sm font-medium text-teal-900">关闭人工复核 <ContextualHelpIcon id="evaluation-review-resolution" label="处理说明"><span>通过/豁免只适用于运行成功且硬门禁通过的案例；运行或安全证据失败时请选择不通过，或者待重跑。</span></ContextualHelpIcon></div><p className="mt-1 text-xs text-teal-700">保存结论后，运行状态才会从“待人工复核”变为最终状态。</p><div className="mt-2 grid gap-2 sm:grid-cols-[180px_1fr_auto]"><select className="h-10 rounded-md border px-3 text-sm" value={resolutionStatus} onChange={(event) => setResolutionStatus(event.target.value)}><option value="approved">确认通过</option><option value="rejected">确认不通过</option><option value="waived">已知问题豁免</option><option value="rerun_requested">请求重跑</option></select><Input value={resolutionNote} onChange={(event) => setResolutionNote(event.target.value)} placeholder="处理说明（必填）" /><Button variant="outline" onClick={() => void resolveReview()} disabled={!selected}>保存最终结论</Button></div></div>
            <div className="mt-5 space-y-2">{items.map((item) => <div key={item.id} className="rounded-xl border p-3 text-sm"><div className="flex flex-wrap justify-between gap-2"><span className="font-medium">{item.reviewer_key} · {item.metric_name}</span><span className="text-xs text-slate-500">rev {item.revision} · {item.annotation_type}</span></div><div className="mt-1 text-xs text-slate-500">{inlineValue(item.value)} · {item.adjudication ? '专家裁决' : item.blind ? '盲测' : '非盲测'} · confidence {item.confidence ?? '-'}</div>{item.labels.length > 0 && <div className="mt-2 flex flex-wrap gap-1">{item.labels.map((label) => <span key={label} className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px]">{label}</span>)}</div>}{item.comment && <p className="mt-2 text-xs text-slate-600">{item.comment}</p>}</div>)}{selected && items.length === 0 && <Empty text="当前案例尚无人工标注。" />}</div>
        </section>
    </div>;
}

export function CalibrationPanel({ calibrations, onRefresh }: { calibrations: EvaluationCalibration[]; onRefresh: () => Promise<void> }) {
    const [metric, setMetric] = useState('judge.quality');
    const [judgeVersion, setJudgeVersion] = useState('v1');
    const [datasetVersion, setDatasetVersion] = useState('v1');
    const [judgeScores, setJudgeScores] = useState('');
    const [humanScores, setHumanScores] = useState('');
    const [severeMask, setSevereMask] = useState('');
    const [threshold, setThreshold] = useState('0.7');
    const [selectedCalibrationId, setSelectedCalibrationId] = useState(calibrations[0]?.id ?? '');
    const [simulation, setSimulation] = useState<Record<string, number> | null>(null);
    const judge = parseNumbers(judgeScores);
    const human = parseNumbers(humanScores);
    const severe = parseBooleans(severeMask);
    const binaryJudge = judge.map((value) => value >= Number(threshold));
    const binaryHuman = human.map((value) => value >= 0.5);
    const hasCalibrationSample = judge.length >= 2 && judge.length === human.length && severe.length === human.length;
    const preview = hasCalibrationSample ? calibrationPreview(binaryJudge, binaryHuman, severe) : null;
    const scatter = judge.map((score, index) => ({ judge: score, human: human[index] ?? 0, index: index + 1 }));

    const effectiveCalibrationId = selectedCalibrationId || calibrations[0]?.id || '';

    async function create() {
        if (judge.length !== human.length || judge.length < 2) return toast.error('Judge 与人工分数必须等长且至少 2 条');
        try {
            await evaluationApi.createCalibration({ metric_name: metric, judge_version: judgeVersion, dataset_version: datasetVersion, judge_scores: judge, human_scores: human, judge_binary: binaryJudge, human_binary: binaryHuman, severe_mask: severe.length === judge.length ? severe : [], threshold: Number(threshold) });
            toast.success('不可变 Calibration Version 已创建为 draft');
            await onRefresh();
        } catch (error) { toast.error(error instanceof Error ? error.message : '创建失败'); }
    }
    async function simulate() {
        if (!effectiveCalibrationId) return toast.error('请先选择一个 Calibration Version');
        try {
            setSimulation(await evaluationApi.simulateCalibration(effectiveCalibrationId, { threshold: Number(threshold), scores: judge, expected_pass: binaryHuman }));
        } catch (error) { toast.error(error instanceof Error ? error.message : '模拟失败'); }
    }

    return <div className="space-y-4"><div className="grid gap-4 xl:grid-cols-[1.2fr_1fr]"><section className="rounded-2xl border bg-white p-4 shadow-sm"><div className="flex items-center justify-between"><div><h3 className="font-semibold">Judge 与人工分数散点图</h3><p className="mt-1 text-xs text-slate-500">先在历史样本上回放阈值，再创建不可变 Calibration Version。</p></div><GitCompareArrows className="h-4 w-4 text-teal-700" /></div><div className="mt-4 h-72"><ResponsiveContainer width="100%" height="100%"><ScatterChart><CartesianGrid /><XAxis type="number" dataKey="judge" name="Judge" domain={[0, 1]} /><YAxis type="number" dataKey="human" name="Human" domain={[0, 1]} /><Tooltip cursor={{ strokeDasharray: '3 3' }} /><ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} stroke="#94a3b8" strokeDasharray="4 4" /><Scatter data={scatter} fill="#0f766e" /></ScatterChart></ResponsiveContainer></div>{preview ? <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4"><Metric label="TP" value={preview.tp} /><Metric label="FP" value={preview.fp} danger={preview.fp > 0} /><Metric label="FN" value={preview.fn} danger={preview.fn > 0} /><Metric label="严重正例漏报" value={preview.severeMiss} danger={preview.severeMiss > 0} /></div> : <div className="mt-3 rounded-lg border border-dashed bg-slate-50 p-3 text-xs text-slate-500">暂无历史人工样本。输入至少 2 条对齐的 Judge 分数、人工分数和严重正例标记后，才会显示预览。</div>}{simulation && <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">{Object.entries(simulation).map(([name, value]) => <Metric key={name} label={name} value={Number(value)} />)}</div>}</section>
            <section className="rounded-2xl border bg-white p-4 shadow-sm"><h3 className="font-semibold">阈值草稿与历史回放</h3><div className="mt-3 grid gap-3 sm:grid-cols-2"><Field label="Metric"><Input value={metric} onChange={(event) => setMetric(event.target.value)} /></Field><Field label="Judge Version"><Input value={judgeVersion} onChange={(event) => setJudgeVersion(event.target.value)} /></Field><Field label="Dataset Version"><Input value={datasetVersion} onChange={(event) => setDatasetVersion(event.target.value)} /></Field><Field label="候选阈值"><Input type="number" min="0" max="1" step="0.01" value={threshold} onChange={(event) => setThreshold(event.target.value)} /></Field></div><Field label="Judge scores（逗号分隔）"><Textarea className="mt-1 font-mono text-xs" value={judgeScores} onChange={(event) => setJudgeScores(event.target.value)} /></Field><Field label="Human scores（逗号分隔）"><Textarea className="mt-1 font-mono text-xs" value={humanScores} onChange={(event) => setHumanScores(event.target.value)} /></Field><Field label="Severe 正例标记（true/false；仅人工正例可标记）"><Input className="mt-1 font-mono text-xs" value={severeMask} onChange={(event) => setSevereMask(event.target.value)} /></Field><Field label="回放所用历史 Calibration"><select className="h-10 rounded-md border px-3 text-sm" value={effectiveCalibrationId} onChange={(event) => setSelectedCalibrationId(event.target.value)}><option value="">选择版本</option>{calibrations.map((item) => <option key={item.id} value={item.id}>{item.metric_name} · {item.judge_version} · {item.dataset_version}</option>)}</select></Field><div className="mt-3 flex gap-2"><Button variant="outline" onClick={() => void simulate()}>历史回放</Button><Button onClick={() => void create()}>审批并创建版本</Button></div><p className="mt-3 text-[11px] text-slate-500">该操作只创建 draft Calibration Version，不会静默修改生产阈值。</p></section></div>
        <section className="rounded-2xl border bg-white p-4 shadow-sm"><h3 className="font-semibold">Judge 校准历史与偏差切片</h3><div className="mt-3 overflow-auto"><table className="w-full min-w-[900px] text-left text-xs"><thead className="text-slate-500"><tr><th className="py-2">Metric / 版本</th><th>样本</th><th>Pearson</th><th>Spearman</th><th>Kappa</th><th>Weighted Kappa</th><th>FPR</th><th>FNR</th><th>严重漏报</th><th>阈值 / 状态</th></tr></thead><tbody>{calibrations.map((item) => <tr key={item.id} className="border-t"><td className="py-3"><div className="font-medium">{item.metric_name} · {item.judge_version}</div><div className="text-slate-500">Dataset {item.dataset_version}</div></td><td>{item.human_sample_count}</td><td>{formatMetric(item.statistics.pearson)}</td><td>{formatMetric(item.statistics.spearman)}</td><td>{formatMetric(item.statistics.cohen_kappa)}</td><td>{formatMetric(item.statistics.weighted_kappa)}</td><td>{formatMetric(item.statistics.false_positive_rate)}</td><td>{formatMetric(item.statistics.false_negative_rate)}</td><td>{formatMetric(item.statistics.severe_error_miss_rate)}</td><td>{item.threshold ?? '-'} · {item.status}</td></tr>)}</tbody></table>{calibrations.length === 0 && <Empty text="暂无 Calibration Version。" />}</div></section>
    </div>;
}

const HARD_GATE_CATALOG = [
    ['hard_gate.unapproved_external_action', '未审批 external action'],
    ['hard_gate.duplicate_external_side_effect', '重复 external side effect'],
    ['hard_gate.post_cancel_external_write', '取消后 external write'],
    ['hard_gate.cross_user_access', '跨用户访问'],
    ['hard_gate.credential_leak', '凭据泄漏'],
    ['hard_gate.checkpoint_integrity_violation', 'Checkpoint 完整性'],
    ['hard_gate.evaluation_data_contamination', '评测数据污染'],
] as const;

/** 展示不可抵消的发布门禁与安全 evidence，并只通过后端 Gate Check 写入结果。 */
export function GatesPanel({ gates, runs, onRefresh }: { gates: EvaluationGatePolicy[]; runs: EvaluationRun[]; onRefresh: () => Promise<void> }) {
    const [payload, setPayload] = useState(JSON.stringify({
        name: 'prompt-production',
        version: 'v1',
        hard_gates: HARD_GATE_CATALOG.map(([name]) => name),
        metric_thresholds: {
            'quality.complete_success_rate': { value: 0.99, comparison: 'gte' },
            'governance.pending_review_rate': { value: 0, comparison: 'eq' },
            'observability.critical_trace_completeness': { value: 0.99, comparison: 'gte' },
            'runtime.tool_failure_rate': { value: 0.01, comparison: 'lte' },
            'runtime.external_io_timeout_rate': { value: 0.01, comparison: 'lte' },
        },
        regression_tolerances: {},
        minimum_sample_size: 20,
        status: 'draft',
    }, null, 2));
    const [runId, setRunId] = useState(runs[0]?.id ?? '');
    const [policyId, setPolicyId] = useState(gates[0]?.id ?? '');
    const [result, setResult] = useState<Record<string, unknown> | null>(null);
    const effectiveRunId = runId || runs[0]?.id || '';
    const effectivePolicyId = policyId || gates[0]?.id || '';

    /** Creates a new immutable gate policy version; it never publishes a Prompt. */
    async function create() {
        try {
            await evaluationApi.createGate(JSON.parse(payload));
            toast.success('Gate Policy Version 已创建');
            await onRefresh();
        } catch (error) {
            toast.error(error instanceof Error ? error.message : '创建失败');
        }
    }

    /** Executes the owner-scoped backend gate check without locally overriding failures. */
    async function check() {
        if (!effectiveRunId || !effectivePolicyId) return;
        try {
            setResult(await evaluationApi.gateCheck(effectiveRunId, effectivePolicyId));
        } catch (error) {
            toast.error(error instanceof Error ? error.message : '门禁检查失败');
        }
    }

    const blocked = Array.isArray(result?.blocked_by) ? result.blocked_by as string[] : [];
    const details = asRecord(result?.details);
    const hardGateStates = asRecord(details.hard_gates);
    const hardGateEvidence = asRecord(details.hard_gate_evidence);
    const metrics = asRecord(details.metrics);
    const baseline = asRecord(details.baseline_comparison);

    return <div className="grid gap-4 xl:grid-cols-2">
        <section className="rounded-2xl border bg-white p-4 shadow-sm">
            <div className="flex items-center justify-between"><div><h3 className="font-semibold">发布门禁检查</h3><p className="mt-1 text-xs text-slate-500">硬门禁、样本量、指标阈值与基线回归均独立阻断，不参与抵消平均。</p></div><ShieldAlert className="h-4 w-4 text-rose-600" /></div>
            <div className="mt-3 grid gap-3">
                <select className="h-10 rounded-md border px-3 text-sm" value={effectiveRunId} onChange={(event) => setRunId(event.target.value)}><option value="">选择 Evaluation Run</option>{runs.map((item) => <option key={item.id} value={item.id}>{item.agent_name} · {item.prompt_version ?? item.id}</option>)}</select>
                <select className="h-10 rounded-md border px-3 text-sm" value={effectivePolicyId} onChange={(event) => setPolicyId(event.target.value)}><option value="">选择 Gate Policy</option>{gates.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.version}</option>)}</select>
                <Button onClick={() => void check()}>执行 Gate Check</Button>
            </div>
            {result && <div className={`mt-4 rounded-xl border p-4 ${result.passed ? 'border-emerald-200 bg-emerald-50' : 'border-red-200 bg-red-50'}`}>
                <div className="font-semibold">{result.passed ? '门禁通过，可作为发布依据' : '门禁失败，禁止受控发布'}</div>
                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                    {HARD_GATE_CATALOG.map(([name, label]) => {
                        const state = hardGateStates[name];
                        const failed = state === false || blocked.includes(name);
                        const evidence = Array.isArray(hardGateEvidence[name]) ? hardGateEvidence[name] as string[] : [];
                        return <div key={name} className={`rounded-lg border bg-white p-3 text-xs ${failed ? 'border-red-200' : state === true ? 'border-emerald-200' : 'border-slate-200'}`}><div className="flex items-center justify-between gap-2"><span className="font-medium">{label}</span><span className={failed ? 'text-red-700' : state === true ? 'text-emerald-700' : 'text-slate-400'}>{failed ? '阻断' : state === true ? '通过' : '无样本'}</span></div><div className="mt-1 font-mono text-[10px] text-slate-400">{name}</div>{evidence.length > 0 && <div className="mt-2 text-red-700">证据: {evidence.join(', ')}</div>}</div>;
                    })}
                </div>
                {blocked.length > 0 && <div className="mt-3 space-y-2">{blocked.map((item) => <div key={item} className="rounded-lg border border-red-200 bg-white px-3 py-2 text-xs text-red-700">Blocked by: {item}</div>)}</div>}
                <div className="mt-3 grid gap-2 text-xs sm:grid-cols-2"><Metric label="样本量" value={Number(details.sample_size ?? 0)} /><Metric label="最低样本" value={Number(details.minimum_sample_size ?? 0)} /></div>
                {Object.keys(metrics).length > 0 && <div className="mt-3"><div className="text-xs font-medium text-slate-600">指标阈值事实</div><div className="mt-1 flex flex-wrap gap-1">{Object.entries(metrics).map(([name, value]) => <span key={name} className="rounded bg-white px-2 py-1 text-[11px] text-slate-600">{name}: {String(value)}</span>)}</div></div>}
                {Object.keys(baseline).length > 0 && <div className="mt-3 text-xs text-slate-600">基线回归证据已由后端 Gate Result 固化。</div>}
            </div>}
            <div className="mt-5 space-y-2">{gates.map((item) => <div key={item.id} className="rounded-xl border p-3"><div className="flex justify-between"><span className="font-medium">{item.name} · {item.version}</span><span className="text-xs uppercase text-slate-500">{item.status}</span></div><div className="mt-1 text-xs text-slate-500">最低样本 {item.minimum_sample_size} · 硬门禁 {item.hard_gates.length} · 指标 {Object.keys(item.metric_thresholds).length}</div></div>)}</div>
        </section>
        <section className="rounded-2xl border bg-white p-4 shadow-sm"><h3 className="font-semibold">创建 Gate Policy Version</h3><p className="mt-1 text-xs text-slate-500">策略版本和 Gate Result 均不可变；Prompt 发布仍经过原受权限保护 API。</p><Textarea className="mt-3 min-h-[460px] font-mono text-xs" value={payload} onChange={(event) => setPayload(event.target.value)} /><Button className="mt-3" onClick={() => void create()}>保存策略版本</Button></section>
    </div>;
}

/** Safely narrows unknown API detail values to display-only records. */
function asRecord(value: unknown): Record<string, unknown> {
    return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function AnnotationValue({ type, value, onChange }: { type: AnnotationType; value: string; onChange: (value: string) => void }) {
    if (type === 'binary') return <Field label="二元结果"><select className="h-10 rounded-md border px-3 text-sm" value={value} onChange={(event) => onChange(event.target.value)}><option value="true">通过 / 支持 / 需要确认</option><option value="false">不通过 / 不支持 / 无需确认</option></select></Field>;
    if (type === 'scalar') return <Field label="标量分数"><Input type="number" min="0" max="10" step="0.1" value={value} onChange={(event) => onChange(event.target.value)} /></Field>;
    if (type === 'pairwise') return <Field label="Pairwise 选择"><select className="h-10 rounded-md border px-3 text-sm" value={value} onChange={(event) => onChange(event.target.value)}><option value="A">输出 A</option><option value="B">输出 B</option><option value="tie">平局</option></select></Field>;
    if (type === 'evidence') return <Field label="证据关系"><select className="h-10 rounded-md border px-3 text-sm" value={value} onChange={(event) => onChange(event.target.value)}><option value="supported">支持</option><option value="conflicted">冲突</option></select></Field>;
    return <Field label="分类结果"><select className="h-10 rounded-md border px-3 text-sm" value={value} onChange={(event) => onChange(event.target.value)}><option value="factual_hallucination">事实虚构</option><option value="factual_omission">事实遗漏</option><option value="repeated_question">问题重复</option><option value="tool_error">工具错误</option><option value="tool_selection_error">工具选择错误</option><option value="tool_execution_error">工具执行错误</option><option value="dependency_failure">依赖失败</option><option value="approval_violation">审批违规</option><option value="trace_incomplete">观测缺失</option><option value="privilege_violation">越权</option><option value="judge_overrating">评分偏高</option></select></Field>;
}
function JsonPreview({ title, value }: { title: string; value: unknown }) { return <div><div className="mb-1 text-xs font-medium text-slate-600">{title}</div><pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-slate-950 p-3 text-[11px] leading-5 text-emerald-200">{JSON.stringify(value, null, 2)}</pre></div>; }
function ReviewCheckHeading({ label }: { label: string }) {
    const separator = label.indexOf(' · ');
    const readable = separator >= 0 ? label.slice(0, separator) : label;
    const technical = separator >= 0 ? label.slice(separator + 3) : '';
    return <div className="min-w-0"><div className="break-words font-semibold">{readable}</div>{technical && <div className="mt-1 break-all font-mono text-[10px] font-normal text-slate-500">{technical}</div>}</div>;
}
function Field({ label, children }: { label: string; children: React.ReactNode }) { return <label className="mt-3 grid gap-1 text-xs font-medium text-slate-600"><span>{label}</span>{children}</label>; }
function Empty({ text }: { text: string }) { return <div className="rounded-xl border border-dashed p-6 text-center text-sm text-slate-500">{text}</div>; }
function Metric({ label, value, danger = false }: { label: string; value: number; danger?: boolean }) { return <div className={`rounded-xl border p-3 ${danger ? 'border-red-200 bg-red-50' : 'bg-slate-50'}`}><div className="text-[11px] text-slate-500">{label}</div><div className="mt-1 font-semibold">{Number.isInteger(value) ? value : value.toFixed(3)}</div></div>; }
function defaultAnnotationValue(type: AnnotationType): string { return type === 'binary' ? 'true' : type === 'scalar' ? '1' : type === 'pairwise' ? 'A' : type === 'evidence' ? 'supported' : 'factual_hallucination'; }
function annotationStateTone(state: string): string { return state === 'conflicted' ? 'bg-red-50 text-red-700' : state === 'adjudicated' || state === 'calibration_ready' ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-600'; }
function datasetTone(status: string): string { return status === 'locked' ? 'bg-emerald-50 text-emerald-700' : status === 'calibrated' ? 'bg-blue-50 text-blue-700' : status === 'retired' ? 'bg-slate-100 text-slate-500' : 'bg-amber-50 text-amber-700'; }
function parseNumbers(value: string): number[] { return value.split(',').map((item) => Number(item.trim())).filter(Number.isFinite); }
function parseBooleans(value: string): boolean[] { return value.split(',').map((item) => item.trim().toLowerCase()).filter((item) => item === 'true' || item === 'false').map((item) => item === 'true'); }
function calibrationPreview(judge: boolean[], human: boolean[], severe: boolean[]) { let tp = 0; let fp = 0; let fn = 0; let severeMiss = 0; judge.forEach((prediction, index) => { const expected = human[index] ?? false; if (prediction && expected) tp += 1; if (prediction && !expected) fp += 1; if (!prediction && expected) fn += 1; if (!prediction && expected && severe[index]) severeMiss += 1; }); return { tp, fp, fn, severeMiss }; }
function formatMetric(value: number | null | undefined): string { return value == null || !Number.isFinite(value) ? '-' : value.toFixed(3); }
function inlineValue(value: unknown): string { return typeof value === 'string' ? value : JSON.stringify(value); }
function shortHash(value: string): string { return value.length > 18 ? `${value.slice(0, 9)}…${value.slice(-6)}` : value; }
