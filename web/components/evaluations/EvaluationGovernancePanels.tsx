'use client';

import { useState } from 'react';
import { CheckCircle2, GitCompareArrows, LockKeyhole, Scale, ShieldAlert, UserCheck } from 'lucide-react';
import { CartesianGrid, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from 'recharts';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
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
import { toast } from 'sonner';

export function DatasetsPanel({ datasets, suites, onRefresh }: { datasets: EvaluationDataset[]; suites: EvaluationSuite[]; onRefresh: () => Promise<void> }) {
    const [datasetJson, setDatasetJson] = useState(JSON.stringify({ name: 'interview-regression', version: 'v1', source: 'manual', cases: [{ case_key: 'case-001', category: 'interview', input: { session_id: 'fixture-session' }, expected_facts: ['asks one question'], forbidden_claims: ['fabricated experience'], tags: ['smoke'], severity: 'high' }] }, null, 2));
    const [suite, setSuite] = useState({ name: '', agent_name: '', dataset_version_id: '', rubric_version: 'v1' });
    const effectiveDatasetVersionId = suite.dataset_version_id || datasets[0]?.id || '';

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
        <section className="rounded-2xl border bg-white p-4 shadow-sm"><div className="flex items-center justify-between"><div><h3 className="font-semibold">Dataset Versions</h3><p className="mt-1 text-xs text-slate-500">draft → annotating → calibrated → locked；锁定版本不可原地改写。</p></div><LockKeyhole className="h-4 w-4 text-teal-700" /></div><div className="mt-3 space-y-2">{datasets.map((item) => <div key={item.id} className="rounded-xl border p-3"><div className="flex flex-wrap items-start justify-between gap-3"><div><div className="font-medium">{item.name} · {item.version}</div><div className="mt-1 text-xs text-slate-500">{item.case_count} cases · {item.source} · hash {shortHash(item.content_hash)}</div><span className={`mt-2 inline-flex rounded-full px-2 py-0.5 text-[10px] uppercase ${datasetTone(item.status)}`}>{item.status}</span></div><div className="flex flex-wrap gap-2">{item.status === 'draft' && <Button size="sm" variant="outline" onClick={() => void updateStatus(item, 'annotating')}>开始标注</Button>}{['draft', 'annotating'].includes(item.status) && <Button size="sm" variant="outline" onClick={() => void updateStatus(item, 'calibrated')}>标记 calibrated</Button>}{item.status === 'calibrated' && <Button size="sm" onClick={() => void updateStatus(item, 'locked')}><LockKeyhole />锁定版本</Button>}{item.status !== 'retired' && <Button size="sm" variant="ghost" onClick={() => void updateStatus(item, 'retired')}>退役</Button>}</div></div></div>)}{datasets.length === 0 && <Empty text="暂无 Dataset Version。" />}</div><div className="mt-5 border-t pt-4"><h4 className="text-sm font-semibold">创建加密 Dataset Version</h4><p className="mt-1 text-xs text-slate-500">输入与 Golden 由后端加密；列表仅返回摘要。</p><Textarea className="mt-3 min-h-64 font-mono text-xs" value={datasetJson} onChange={(event) => setDatasetJson(event.target.value)} /><Button className="mt-3" onClick={() => void createDataset()}>创建新版本</Button></div></section>
        <section className="rounded-2xl border bg-white p-4 shadow-sm"><h3 className="font-semibold">Evaluation Suites</h3><div className="mt-3 space-y-2">{suites.map((item) => <div key={item.id} className="rounded-xl border p-3"><div className="font-medium">{item.name}</div><div className="mt-1 text-xs text-slate-500">{item.agent_name} · Rubric {item.rubric_version}</div><div className="mt-1 font-mono text-[10px] text-slate-400">Dataset {item.dataset_version_id}</div></div>)}{suites.length === 0 && <Empty text="暂无 Evaluation Suite。" />}</div><div className="mt-5 grid gap-3 border-t pt-4"><Input placeholder="套件名称" value={suite.name} onChange={(event) => setSuite({ ...suite, name: event.target.value })} /><Input placeholder="生产 Agent allowlist 名称" value={suite.agent_name} onChange={(event) => setSuite({ ...suite, agent_name: event.target.value })} /><select className="h-10 rounded-md border px-3 text-sm" value={effectiveDatasetVersionId} onChange={(event) => setSuite({ ...suite, dataset_version_id: event.target.value })}><option value="">选择 Dataset Version</option>{datasets.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.version} · {item.status}</option>)}</select><Input placeholder="Rubric 版本" value={suite.rubric_version} onChange={(event) => setSuite({ ...suite, rubric_version: event.target.value })} /><Button onClick={() => void createSuite()}>创建套件</Button></div></section>
    </div>;
}

type AnnotationType = 'binary' | 'scalar' | 'categorical' | 'pairwise' | 'evidence';

export function AnnotationsPanel({ queue, onRefresh }: { queue: Array<EvaluationCaseRun & { agent_name: string }>; onRefresh: () => Promise<void> }) {
    const [selected, setSelected] = useState<string | null>(null);
    const [items, setItems] = useState<EvaluationAnnotation[]>([]);
    const [detail, setDetail] = useState<EvaluationCaseRunDetail | null>(null);
    const [annotationType, setAnnotationType] = useState<AnnotationType>('binary');
    const [metric, setMetric] = useState('quality.overall');
    const [reviewer, setReviewer] = useState('reviewer-a');
    const [rubricVersion, setRubricVersion] = useState('v1');
    const [value, setValue] = useState('true');
    const [labels, setLabels] = useState('');
    const [comment, setComment] = useState('');
    const [confidence, setConfidence] = useState('1');
    const [blind, setBlind] = useState(true);
    const [evidenceStart, setEvidenceStart] = useState('0');
    const [evidenceEnd, setEvidenceEnd] = useState('1');
    const [evidenceText, setEvidenceText] = useState('');
    const state = deriveAnnotationState(items);

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
                metric_name: metric,
                value: parsedValue(),
                reviewer_key: reviewer,
                blind,
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
    async function adjudicate() {
        const source = items.find((item) => !item.adjudication);
        if (!source || !selected) return;
        try {
            await evaluationApi.adjudicate(source.id, { metric_name: metric, value: parsedValue(), comment: comment || '专家裁决' });
            await load(selected);
            toast.success('专家裁决已追加，历史 revision 保留');
            await onRefresh();
        } catch (error) { toast.error(error instanceof Error ? error.message : '裁决失败'); }
    }

    return <div className="grid gap-4 xl:grid-cols-[340px_minmax(0,1fr)]">
        <section className="rounded-2xl border bg-white p-4 shadow-sm"><div className="flex items-center justify-between"><div><h3 className="font-semibold">人工复核队列</h3><p className="mt-1 text-xs text-slate-500">失败、硬门禁、低置信度与抽检案例。</p></div><UserCheck className="h-4 w-4 text-teal-700" /></div><div className="mt-3 max-h-[760px] space-y-2 overflow-auto">{queue.map((item) => <button key={item.id} onClick={() => void load(item.id)} className={`w-full rounded-xl border p-3 text-left ${selected === item.id ? 'border-teal-500 bg-teal-50' : 'hover:bg-slate-50'}`}><div className="flex justify-between"><span className="font-medium">{item.agent_name}</span><span className="text-[10px] uppercase text-slate-500">{item.status}</span></div><div className="mt-1 font-mono text-[11px] text-slate-500">{item.case_id}</div><div className="mt-1 text-xs text-slate-500">{item.error_category ?? (item.hard_gate_passed ? '抽样/低置信度' : '硬门禁失败')}</div></button>)}{queue.length === 0 && <Empty text="暂无待复核案例。" />}</div></section>
        <section className="min-w-0 rounded-2xl border bg-white p-4 shadow-sm"><div className="flex flex-wrap justify-between gap-2"><div><h3 className="font-semibold">双人盲化标注与裁决</h3><p className="mt-1 text-xs text-slate-500">支持二元、标量、分类、Pairwise 与证据区间；写入 append-only revision。</p></div><span className={`h-fit rounded-full px-3 py-1 text-xs ${annotationStateTone(state)}`}>{state}</span></div>
            {detail ? <><div className="mt-4 grid gap-3 lg:grid-cols-2"><JsonPreview title="案例输入 / 证据" value={{ input: detail.case.input, expected: detail.case.expected }} /><JsonPreview title="待评输出" value={detail.actual_output} /></div>{annotationType === 'pairwise' && <div className="mt-3 grid gap-3 lg:grid-cols-2"><JsonPreview title="盲化输出 A" value={detail.pairwise_outputs.A} /><JsonPreview title="盲化输出 B" value={detail.pairwise_outputs.B ?? '当前运行未关联可用基线'} /></div>}</> : <Empty text="从左侧选择一个案例。" />}
            <div className="mt-4 grid gap-3 border-t pt-4 sm:grid-cols-2 lg:grid-cols-4"><Field label="标注类型"><select className="h-10 rounded-md border px-3 text-sm" value={annotationType} onChange={(event) => { const type = event.target.value as AnnotationType; setAnnotationType(type); setValue(defaultAnnotationValue(type)); }}><option value="binary">二元</option><option value="scalar">标量</option><option value="categorical">分类</option><option value="pairwise">Pairwise</option><option value="evidence">证据区间</option></select></Field><Field label="Metric"><Input value={metric} onChange={(event) => setMetric(event.target.value)} /></Field><Field label="Reviewer"><select className="h-10 rounded-md border px-3 text-sm" value={reviewer} onChange={(event) => setReviewer(event.target.value)}><option value="reviewer-a">Reviewer A</option><option value="reviewer-b">Reviewer B</option><option value="reviewer-c">Reviewer C</option></select></Field><Field label="Rubric Version"><Input value={rubricVersion} onChange={(event) => setRubricVersion(event.target.value)} /></Field><AnnotationValue type={annotationType} value={value} onChange={setValue} /><Field label="置信度 0-1"><Input type="number" min="0" max="1" step="0.05" value={confidence} onChange={(event) => setConfidence(event.target.value)} /></Field><Field label="标签（逗号分隔）"><Input value={labels} onChange={(event) => setLabels(event.target.value)} placeholder="事实虚构, 工具错误" /></Field><label className="flex h-10 items-center gap-2 self-end rounded-md border px-3 text-sm"><Checkbox checked={blind} onCheckedChange={setBlind} />盲化标注</label></div>
            {annotationType === 'evidence' && <div className="mt-3 grid gap-3 sm:grid-cols-[120px_120px_1fr]"><Field label="开始位置"><Input type="number" min="0" value={evidenceStart} onChange={(event) => setEvidenceStart(event.target.value)} /></Field><Field label="结束位置"><Input type="number" min="1" value={evidenceEnd} onChange={(event) => setEvidenceEnd(event.target.value)} /></Field><Field label="证据文本"><Input value={evidenceText} onChange={(event) => setEvidenceText(event.target.value)} placeholder="仅填写业务证据，不得粘贴认证材料" /></Field></div>}
            <Textarea className="mt-3" value={comment} onChange={(event) => setComment(event.target.value)} placeholder="标注说明 / 裁决理由" /><div className="mt-3 flex flex-wrap gap-2"><Button onClick={() => void add()} disabled={!selected}><CheckCircle2 />追加标注</Button><Button variant="outline" onClick={() => void adjudicate()} disabled={state !== 'conflicted'}><Scale />专家裁决</Button></div>
            <div className="mt-5 space-y-2">{items.map((item) => <div key={item.id} className="rounded-xl border p-3 text-sm"><div className="flex flex-wrap justify-between gap-2"><span className="font-medium">{item.reviewer_key} · {item.metric_name}</span><span className="text-xs text-slate-500">rev {item.revision} · {item.annotation_type}</span></div><div className="mt-1 text-xs text-slate-500">{inlineValue(item.value)} · {item.adjudication ? '专家裁决' : item.blind ? '盲测' : '非盲测'} · confidence {item.confidence ?? '-'}</div>{item.labels.length > 0 && <div className="mt-2 flex flex-wrap gap-1">{item.labels.map((label) => <span key={label} className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px]">{label}</span>)}</div>}{item.comment && <p className="mt-2 text-xs text-slate-600">{item.comment}</p>}</div>)}{selected && items.length === 0 && <Empty text="当前案例尚无人工标注。" />}</div>
        </section>
    </div>;
}

export function CalibrationPanel({ calibrations, onRefresh }: { calibrations: EvaluationCalibration[]; onRefresh: () => Promise<void> }) {
    const [metric, setMetric] = useState('judge.quality');
    const [judgeVersion, setJudgeVersion] = useState('v1');
    const [datasetVersion, setDatasetVersion] = useState('v1');
    const [judgeScores, setJudgeScores] = useState('0.9,0.2,0.7,0.45');
    const [humanScores, setHumanScores] = useState('1,0,1,0');
    const [severeMask, setSevereMask] = useState('false,true,false,true');
    const [threshold, setThreshold] = useState('0.7');
    const [selectedCalibrationId, setSelectedCalibrationId] = useState(calibrations[0]?.id ?? '');
    const [simulation, setSimulation] = useState<Record<string, number> | null>(null);
    const judge = parseNumbers(judgeScores);
    const human = parseNumbers(humanScores);
    const severe = parseBooleans(severeMask);
    const binaryJudge = judge.map((value) => value >= Number(threshold));
    const binaryHuman = human.map((value) => value >= 0.5);
    const preview = calibrationPreview(binaryJudge, binaryHuman, severe);
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

    return <div className="space-y-4"><div className="grid gap-4 xl:grid-cols-[1.2fr_1fr]"><section className="rounded-2xl border bg-white p-4 shadow-sm"><div className="flex items-center justify-between"><div><h3 className="font-semibold">Judge 与人工分数散点图</h3><p className="mt-1 text-xs text-slate-500">先在历史样本上回放阈值，再创建不可变 Calibration Version。</p></div><GitCompareArrows className="h-4 w-4 text-teal-700" /></div><div className="mt-4 h-72"><ResponsiveContainer width="100%" height="100%"><ScatterChart><CartesianGrid /><XAxis type="number" dataKey="judge" name="Judge" domain={[0, 1]} /><YAxis type="number" dataKey="human" name="Human" domain={[0, 1]} /><Tooltip cursor={{ strokeDasharray: '3 3' }} /><ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} stroke="#94a3b8" strokeDasharray="4 4" /><Scatter data={scatter} fill="#0f766e" /></ScatterChart></ResponsiveContainer></div><div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4"><Metric label="TP" value={preview.tp} /><Metric label="FP" value={preview.fp} danger={preview.fp > 0} /><Metric label="FN" value={preview.fn} danger={preview.fn > 0} /><Metric label="严重漏报" value={preview.severeMiss} danger={preview.severeMiss > 0} /></div>{simulation && <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">{Object.entries(simulation).map(([name, value]) => <Metric key={name} label={name} value={Number(value)} />)}</div>}</section>
            <section className="rounded-2xl border bg-white p-4 shadow-sm"><h3 className="font-semibold">阈值草稿与历史回放</h3><div className="mt-3 grid gap-3 sm:grid-cols-2"><Field label="Metric"><Input value={metric} onChange={(event) => setMetric(event.target.value)} /></Field><Field label="Judge Version"><Input value={judgeVersion} onChange={(event) => setJudgeVersion(event.target.value)} /></Field><Field label="Dataset Version"><Input value={datasetVersion} onChange={(event) => setDatasetVersion(event.target.value)} /></Field><Field label="候选阈值"><Input type="number" min="0" max="1" step="0.01" value={threshold} onChange={(event) => setThreshold(event.target.value)} /></Field></div><Field label="Judge scores（逗号分隔）"><Textarea className="mt-1 font-mono text-xs" value={judgeScores} onChange={(event) => setJudgeScores(event.target.value)} /></Field><Field label="Human scores（逗号分隔）"><Textarea className="mt-1 font-mono text-xs" value={humanScores} onChange={(event) => setHumanScores(event.target.value)} /></Field><Field label="Severe mask（true/false）"><Input className="mt-1 font-mono text-xs" value={severeMask} onChange={(event) => setSevereMask(event.target.value)} /></Field><Field label="回放所用历史 Calibration"><select className="h-10 rounded-md border px-3 text-sm" value={effectiveCalibrationId} onChange={(event) => setSelectedCalibrationId(event.target.value)}><option value="">选择版本</option>{calibrations.map((item) => <option key={item.id} value={item.id}>{item.metric_name} · {item.judge_version} · {item.dataset_version}</option>)}</select></Field><div className="mt-3 flex gap-2"><Button variant="outline" onClick={() => void simulate()}>历史回放</Button><Button onClick={() => void create()}>审批并创建版本</Button></div><p className="mt-3 text-[11px] text-slate-500">该操作只创建 draft Calibration Version，不会静默修改生产阈值。</p></section></div>
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
function Field({ label, children }: { label: string; children: React.ReactNode }) { return <label className="mt-3 grid gap-1 text-xs font-medium text-slate-600"><span>{label}</span>{children}</label>; }
function Empty({ text }: { text: string }) { return <div className="rounded-xl border border-dashed p-6 text-center text-sm text-slate-500">{text}</div>; }
function Metric({ label, value, danger = false }: { label: string; value: number; danger?: boolean }) { return <div className={`rounded-xl border p-3 ${danger ? 'border-red-200 bg-red-50' : 'bg-slate-50'}`}><div className="text-[11px] text-slate-500">{label}</div><div className="mt-1 font-semibold">{Number.isInteger(value) ? value : value.toFixed(3)}</div></div>; }
function defaultAnnotationValue(type: AnnotationType): string { return type === 'binary' ? 'true' : type === 'scalar' ? '1' : type === 'pairwise' ? 'A' : type === 'evidence' ? 'supported' : 'factual_hallucination'; }
function annotationStateTone(state: string): string { return state === 'conflicted' ? 'bg-red-50 text-red-700' : state === 'adjudicated' || state === 'calibration_ready' ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-600'; }
function datasetTone(status: string): string { return status === 'locked' ? 'bg-emerald-50 text-emerald-700' : status === 'calibrated' ? 'bg-blue-50 text-blue-700' : status === 'retired' ? 'bg-slate-100 text-slate-500' : 'bg-amber-50 text-amber-700'; }
function parseNumbers(value: string): number[] { return value.split(',').map((item) => Number(item.trim())).filter(Number.isFinite); }
function parseBooleans(value: string): boolean[] { return value.split(',').map((item) => item.trim().toLowerCase()).filter((item) => item === 'true' || item === 'false').map((item) => item === 'true'); }
function calibrationPreview(judge: boolean[], human: boolean[], severe: boolean[]) { let tp = 0; let fp = 0; let fn = 0; let severeMiss = 0; judge.forEach((prediction, index) => { const expected = human[index] ?? false; if (prediction && expected) tp += 1; if (prediction && !expected) fp += 1; if (!prediction && expected) fn += 1; if (!prediction && severe[index]) severeMiss += 1; }); return { tp, fp, fn, severeMiss }; }
function formatMetric(value: number | null | undefined): string { return value == null || !Number.isFinite(value) ? '-' : value.toFixed(3); }
function inlineValue(value: unknown): string { return typeof value === 'string' ? value : JSON.stringify(value); }
function shortHash(value: string): string { return value.length > 18 ? `${value.slice(0, 9)}…${value.slice(-6)}` : value; }
