'use client';

import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, Eye, FlaskConical, UserCheck } from 'lucide-react';
import {
    CartesianGrid,
    Legend,
    Line,
    LineChart,
    PolarAngleAxis,
    PolarGrid,
    PolarRadiusAxis,
    Radar,
    RadarChart,
    ResponsiveContainer,
    Tooltip,
    XAxis,
    YAxis,
} from 'recharts';
import { Button } from '@/components/ui/button';
import type { EvaluationOverview, EvaluationRegression, EvaluationTrendPoint } from '@/lib/api/evaluations';
import { overviewCards } from '@/lib/evaluationMetrics';
import { loadAcknowledgedRegressionIds, saveAcknowledgedRegressionIds } from '@/lib/evaluationRegressionAcknowledgements';
import { buildEvaluationTrendPresentation, formatTrendLatency, formatTrendPercentage } from '@/lib/evaluationTrendPresentation';

interface Props {
    overview: EvaluationOverview | null;
    trends: EvaluationTrendPoint[];
    regressions: EvaluationRegression[];
    onOpenRun: (runId: string) => void;
    onRequestReview: (runId: string) => Promise<void>;
}

const cardTones: Record<string, string> = {
    blue: 'from-blue-50 to-white border-blue-100', teal: 'from-teal-50 to-white border-teal-100', emerald: 'from-emerald-50 to-white border-emerald-100',
    violet: 'from-violet-50 to-white border-violet-100', cyan: 'from-cyan-50 to-white border-cyan-100', indigo: 'from-indigo-50 to-white border-indigo-100',
    fuchsia: 'from-fuchsia-50 to-white border-fuchsia-100', amber: 'from-amber-50 to-white border-amber-100', orange: 'from-orange-50 to-white border-orange-100',
    rose: 'from-rose-50 to-white border-rose-100', red: 'from-red-50 to-white border-red-100', slate: 'from-slate-50 to-white border-slate-200',
    purple: 'from-purple-50 to-white border-purple-100', green: 'from-green-50 to-white border-green-100',
};

/** Renders source-separated health metrics, filters and regression actions. */
export function EvaluationOverviewPanel({ overview, trends, regressions, onOpenRun, onRequestReview }: Props) {
    const [agent, setAgent] = useState('all');
    const [agentVersion, setAgentVersion] = useState('all');
    const [prompt, setPrompt] = useState('all');
    const [promptVersion, setPromptVersion] = useState('all');
    const [dataset, setDataset] = useState('all');
    const [model, setModel] = useState('all');
    const [environment, setEnvironment] = useState('all');
    const [range, setRange] = useState('all');
    const [acknowledged, setAcknowledged] = useState<Set<string>>(() => new Set());

    useEffect(() => {
        setAcknowledged(loadAcknowledgedRegressionIds(window.localStorage));
    }, []);

    function acknowledgeRegression(runId: string): void {
        setAcknowledged((current) => {
            const next = new Set(current);
            next.add(runId);
            saveAcknowledgedRegressionIds(next, window.localStorage);
            return next;
        });
    }

    const options = useMemo(() => ({
        agents: unique(trends.map((item) => item.agent_name)),
        agentVersions: unique(trends.map((item) => item.agent_version)),
        prompts: unique(trends.map((item) => item.prompt_name).filter(Boolean) as string[]),
        promptVersions: unique(trends.map((item) => item.prompt_version).filter(Boolean) as string[]),
        datasets: unique(trends.map((item) => item.dataset_version)),
        models: unique(trends.map((item) => item.model_config_hash)),
        environments: unique(trends.map((item) => item.environment)),
    }), [trends]);
    const filtered = useMemo(() => {
        const newestTimestamp = trends.reduce((latest, item) => Math.max(latest, new Date(item.created_at).getTime() || 0), 0);
        const cutoff = range === 'all' ? null : newestTimestamp - Number(range) * 86_400_000;
        return trends.filter((item) => (agent === 'all' || item.agent_name === agent)
            && (agentVersion === 'all' || item.agent_version === agentVersion)
            && (prompt === 'all' || item.prompt_name === prompt)
            && (promptVersion === 'all' || item.prompt_version === promptVersion)
            && (dataset === 'all' || item.dataset_version === dataset)
            && (model === 'all' || item.model_config_hash === model)
            && (environment === 'all' || item.environment === environment)
            && (cutoff == null || new Date(item.created_at).getTime() >= cutoff));
    }, [agent, agentVersion, dataset, environment, model, prompt, promptVersion, range, trends]);
    const trendPresentation = useMemo(() => buildEvaluationTrendPresentation(filtered), [filtered]);

    if (!overview) return <div className="rounded-2xl border border-dashed p-8 text-sm text-slate-500">暂无总览数据。</div>;
    const capabilityData = [
        capability('结果质量', overview.complete_success_rate),
        capability('事实忠实度', overview.factual_support_rate),
        capability('轨迹质量', overview.semantic_success_rate),
        capability('工具使用', overview.tool_call_accuracy),
        capability('RAG/记忆', overview.factual_support_rate),
        capability('可靠性', overview.runtime_success_rate),
        capability('安全性', overview.hard_gate_pass_rate),
        capability('效率', overview.latency_compliance_rate),
    ];
    const visibleRegressions = regressions.filter((item) => !acknowledged.has(item.run_id));
    const cards = overviewCards(overview);
    const cardGroups = [
        { key: 'quality', title: '结果与质量' },
        { key: 'governance', title: '安全与治理' },
        { key: 'stability', title: '稳定性与效率' },
        { key: 'observability', title: '观测上报' },
    ] as const;

    return <div className="space-y-5">
        {cardGroups.map((group) => <section key={group.key} className="space-y-2"><h3 className="text-sm font-semibold text-slate-700">{group.title}</h3><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{cards.filter((card) => card.group === group.key).map((card) => <div key={card.key} className={`rounded-2xl border bg-gradient-to-br p-4 shadow-sm ${cardTones[card.tone]}`}><div className="text-xs font-medium text-slate-500">{card.label}</div><div className="mt-2 text-2xl font-semibold text-slate-900">{card.value}</div></div>)}</div></section>)}

        <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex flex-col justify-between gap-3 lg:flex-row lg:items-end">
                <div><h3 className="font-semibold text-slate-900">版本趋势</h3><p className="mt-1 text-xs text-slate-500">完全成功率与 P95 延迟分开展示；筛选不会混合不同版本上下文。</p></div>
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-8">
                    <Filter value={agent} onChange={setAgent} label="全部 Agent" options={options.agents} />
                    <Filter value={agentVersion} onChange={setAgentVersion} label="全部 Agent 版本" options={options.agentVersions} />
                    <Filter value={prompt} onChange={setPrompt} label="全部 Prompt" options={options.prompts} />
                    <Filter value={promptVersion} onChange={setPromptVersion} label="全部 Prompt 版本" options={options.promptVersions} />
                    <Filter value={dataset} onChange={setDataset} label="全部 Dataset" options={options.datasets} />
                    <Filter value={model} onChange={setModel} label="全部模型配置" options={options.models} compact />
                    <Filter value={environment} onChange={setEnvironment} label="全部环境" options={options.environments} />
                    <select className="h-9 rounded-lg border border-slate-200 bg-white px-2 text-xs" value={range} onChange={(event) => setRange(event.target.value)}><option value="all">全部时间</option><option value="7">最近 7 天</option><option value="30">最近 30 天</option><option value="90">最近 90 天</option></select>
                </div>
            </div>
            {filtered.length ? <div className="mt-4 grid gap-4 xl:grid-cols-2">
                <TrendChartCard title="评测通过情况" description="完全成功率；纵轴统一为百分比。">
                    {trendPresentation.hasQualityData ? <ResponsiveContainer width="100%" height="100%"><LineChart data={trendPresentation.qualityData}><CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" /><XAxis dataKey="name" tick={{ fontSize: 11 }} /><YAxis domain={[0, 100]} tick={{ fontSize: 11 }} tickFormatter={(value) => formatTrendPercentage(Number(value))} width={52} /><Tooltip formatter={(value, name) => [formatTrendPercentage(typeof value === 'number' ? value : null), name]} /><Legend /><Line type="monotone" dataKey="success" name="完全成功率" stroke="#2563eb" strokeWidth={2} /></LineChart></ResponsiveContainer> : <Empty text="暂无可展示的完全成功率。" />}
                </TrendChartCard>
                <TrendChartCard title="响应延迟" description={`仅展示 P95 延迟；统一换算为${trendPresentation.latencyUnit}。`}>
                    {trendPresentation.hasLatencyData ? <ResponsiveContainer width="100%" height="100%"><LineChart data={trendPresentation.latencyData}><CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" /><XAxis dataKey="name" tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} tickFormatter={(value) => formatTrendLatency(Number(value), trendPresentation.latencyUnit)} width={70} /><Tooltip formatter={(value, name) => [formatTrendLatency(typeof value === 'number' ? value : null, trendPresentation.latencyUnit), name]} /><Legend /><Line type="monotone" dataKey="latency" name="P95 延迟" stroke="#f97316" strokeWidth={2} /></LineChart></ResponsiveContainer> : <Empty text="暂无可展示的 P95 延迟。" />}
                </TrendChartCard>
            </div> : <div className="mt-4 h-40"><Empty text="当前筛选条件下暂无趋势样本。" /></div>}
            {filtered.length > 0 && <div className="mt-3 overflow-auto"><table className="w-full min-w-[760px] text-left text-xs"><thead className="text-slate-500"><tr><th className="py-2">版本上下文</th><th>样本</th><th>P50/P95 延迟</th><th>P50/P95 Token</th><th>总 Token</th></tr></thead><tbody>{filtered.slice(-8).reverse().map((item) => <tr key={item.run_id} className="border-t"><td className="py-2"><div className="font-medium text-slate-800">{item.agent_name} · {item.agent_version}</div><div className="text-slate-500">{item.prompt_name ?? '无 Prompt'} {item.prompt_version ?? ''} · {item.dataset_version}</div></td><td>{item.sample_count}</td><td>{formatTrendLatency(item.p50_latency_ms, trendPresentation.latencyUnit)} / {formatTrendLatency(item.p95_latency_ms, trendPresentation.latencyUnit)}</td><td>{formatNumber(item.p50_tokens)} / {formatNumber(item.p95_tokens)}</td><td>{formatNumber(item.token_total)}</td></tr>)}</tbody></table></div>}
        </section>

        <div className="grid gap-4 xl:grid-cols-[1fr_1.2fr]">
            <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"><h3 className="font-semibold text-slate-900">Agent 能力雷达</h3><p className="mt-1 text-xs text-slate-500">仅使用可追溯聚合指标；无样本维度显示为灰色。</p><div className="mt-3 h-72"><ResponsiveContainer width="100%" height="100%"><RadarChart data={capabilityData}><PolarGrid /><PolarAngleAxis dataKey="dimension" tick={{ fontSize: 11 }} /><PolarRadiusAxis domain={[0, 100]} tick={{ fontSize: 10 }} /><Radar dataKey="score" stroke="#0f766e" fill="#14b8a6" fillOpacity={0.25} /></RadarChart></ResponsiveContainer></div></section>
            <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"><h3 className="font-semibold text-slate-900">Agent × 指标矩阵</h3><div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">{capabilityData.map((item) => <div key={item.dimension} className={`rounded-xl border p-3 ${matrixTone(item.score, item.available)}`}><div className="text-xs text-slate-500">{item.dimension}</div><div className="mt-1 font-semibold">{item.available ? `${item.score.toFixed(1)}%` : '样本不足'}</div></div>)}</div><div className="mt-4 flex flex-wrap gap-3 text-[11px] text-slate-500"><LegendDot color="bg-emerald-500" text="达到门槛" /><LegendDot color="bg-amber-500" text="接近门槛" /><LegendDot color="bg-red-500" text="阻断发布" /><LegendDot color="bg-slate-300" text="样本不足" /></div></section>
        </div>

        <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center justify-between"><div><h3 className="font-semibold text-slate-900">回归告警</h3><p className="mt-1 text-xs text-slate-500">告警保留 Agent、Prompt、模型、Dataset 和基线差异上下文。</p></div><span className="rounded-full bg-rose-50 px-3 py-1 text-xs font-medium text-rose-700">{visibleRegressions.length} 待确认</span></div>
            <div className="mt-4 space-y-3">{visibleRegressions.length === 0 && <Empty text="暂无未确认回归。" />}{visibleRegressions.map((item) => <article key={item.run_id} className={`rounded-xl border p-4 ${item.hard_gate_blocked ? 'border-red-200 bg-red-50/60' : 'border-amber-200 bg-amber-50/60'}`}>
                <div className="flex flex-col justify-between gap-3 md:flex-row"><div><div className="flex items-center gap-2"><AlertTriangle className={`h-4 w-4 ${item.hard_gate_blocked ? 'text-red-600' : 'text-amber-600'}`} /><span className="font-medium text-slate-900">{item.agent_name} · {item.prompt_name ?? '无 Prompt'} {item.prompt_version ?? ''}</span><span className="rounded-full bg-white px-2 py-0.5 text-[10px] uppercase text-slate-500">{item.severity}</span></div><div className="mt-2 text-xs text-slate-600">模型 {shortHash(item.model_config_hash)} · Dataset {item.dataset_version} · 失败案例 {item.failed_case_count} · 回归指标 {item.regression_count} · 硬门禁失败 {item.hard_gate_failure_count}</div><div className="mt-2 flex flex-wrap gap-2">{Object.entries(item.metric_deltas).slice(0, 6).map(([name, delta]) => <span key={name} className="rounded-md bg-white px-2 py-1 text-[11px] text-slate-600">{name} {delta > 0 ? '+' : ''}{delta.toFixed(3)}</span>)}</div></div><div className="flex flex-wrap items-start gap-2"><Button size="sm" variant="outline" onClick={() => onOpenRun(item.run_id)}><Eye className="mr-1 h-3.5 w-3.5" />查看案例</Button><Button size="sm" variant="outline" onClick={() => void onRequestReview(item.run_id)}><UserCheck className="mr-1 h-3.5 w-3.5" />进入复核</Button><Button size="sm" variant="outline" onClick={() => onOpenRun(item.run_id)}><FlaskConical className="mr-1 h-3.5 w-3.5" />沉淀回归集</Button><Button size="sm" variant="ghost" onClick={() => acknowledgeRegression(item.run_id)}><CheckCircle2 className="mr-1 h-3.5 w-3.5" />本次已确认</Button></div></div>
            </article>)}</div>
        </section>
    </div>;
}

function TrendChartCard({ title, description, children }: { title: string; description: string; children: React.ReactNode }) {
    return <div className="rounded-xl border border-slate-100 bg-slate-50/50 p-3"><div><h4 className="text-sm font-medium text-slate-800">{title}</h4><p className="mt-0.5 text-xs text-slate-500">{description}</p></div><div className="mt-3 h-64">{children}</div></div>;
}
function Filter({ value, onChange, label, options, compact = false }: { value: string; onChange: (value: string) => void; label: string; options: string[]; compact?: boolean }) {
    return <select className={`h-9 rounded-lg border border-slate-200 bg-white px-2 text-xs ${compact ? 'max-w-44' : ''}`} value={value} onChange={(event) => onChange(event.target.value)}><option value="all">{label}</option>{options.map((option) => <option key={option} value={option}>{compact ? shortHash(option) : option}</option>)}</select>;
}
function Empty({ text }: { text: string }) { return <div className="flex h-full min-h-24 items-center justify-center rounded-xl border border-dashed border-slate-200 text-sm text-slate-500">{text}</div>; }
function LegendDot({ color, text }: { color: string; text: string }) { return <span className="inline-flex items-center gap-1"><span className={`h-2 w-2 rounded-full ${color}`} />{text}</span>; }
function unique(values: string[]): string[] { return [...new Set(values)].sort(); }
function capability(dimension: string, value: number | null) { return { dimension, score: Number(value ?? 0) * 100, available: value != null }; }
function matrixTone(score: number, available: boolean): string { if (!available) return 'border-slate-200 bg-slate-50'; if (score >= 80) return 'border-emerald-200 bg-emerald-50'; if (score >= 60) return 'border-amber-200 bg-amber-50'; return 'border-red-200 bg-red-50'; }
function formatNumber(value: number | null): string { return value == null || !Number.isFinite(value) ? '-' : Math.round(value).toLocaleString('zh-CN'); }
function shortHash(value: string): string { return value.length > 18 ? `${value.slice(0, 9)}…${value.slice(-6)}` : value; }
