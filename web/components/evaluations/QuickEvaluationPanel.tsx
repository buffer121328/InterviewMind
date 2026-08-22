'use client';

import { useMemo, useState } from 'react';
import {
    Bot,
    CheckCircle2,
    Clock3,
    Coins,
    Database,
    Gauge,
    Play,
    Scale,
    Sparkles,
    TriangleAlert,
} from 'lucide-react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { ContextualHelpIcon } from '@/components/ContextualHelpIcon';
import {
    evaluationApi,
    type EvaluationAgentName,
    type EvaluationCatalog,
    type EvaluationCatalogAgent,
    type EvaluationQuickMode,
    type EvaluationQuickModeName,
    type EvaluationRun,
} from '@/lib/api/evaluations';
import {
    parseEvaluationPromptCandidate,
    promptCandidateMatches,
    type EvaluationPromptCandidate,
} from '@/lib/evaluationQuickStart';
import { formatEvaluationScopeSummary } from '@/lib/evaluationScopePresentation';
import { useInterviewStore } from '@/store/useInterviewStore';
import { RecentEvaluationResults } from './RecentEvaluationResults';

interface QuickEvaluationPanelProps {
    catalog: EvaluationCatalog | null;
    runs: EvaluationRun[];
    loading: boolean;
    onRefresh: () => Promise<void>;
    onOpenRun: (runId: string) => void;
}

/**
 * Renders the default one-click evaluation workflow.
 * API keys are read from Zustand only when the user starts a run and are never rendered or logged.
 */
export function QuickEvaluationPanel({
    catalog,
    runs,
    loading,
    onRefresh,
    onOpenRun,
}: QuickEvaluationPanelProps) {
    const getApiConfigForRequest = useInterviewStore(state => state.getApiConfigForRequest);
    const smartModel = useInterviewStore(state => (
        state.apiConfig.models.find(model => model.id === state.apiConfig.smartModelId) ?? null
    ));
    const fastModel = useInterviewStore(state => (
        state.apiConfig.models.find(model => model.id === state.apiConfig.fastModelId) ?? null
    ));
    const [candidate, setCandidate] = useState<EvaluationPromptCandidate | null>(() => (
        typeof window === 'undefined'
            ? null
            : parseEvaluationPromptCandidate(localStorage.getItem('evaluationPromptCandidate'))
    ));
    const [selectedAgentName, setSelectedAgentName] = useState<EvaluationAgentName | null>(null);
    const [selectedModeName, setSelectedModeName] = useState<EvaluationQuickModeName>('quick');
    const [compareProductionOverride, setCompareProductionOverride] = useState<boolean | null>(null);
    const [submitting, setSubmitting] = useState(false);

    const candidateAgent = candidate
        ? catalog?.agents.find(agent => agent.prompt_name === candidate.name) ?? null
        : null;
    const effectiveAgentName = selectedAgentName
        ?? candidateAgent?.name
        ?? catalog?.agents[0]?.name
        ?? null;

    const selectedAgent = useMemo(
        () => catalog?.agents.find(agent => agent.name === effectiveAgentName) ?? null,
        [catalog, effectiveAgentName],
    );
    const selectedMode = useMemo(
        () => catalog?.modes.find(mode => mode.name === selectedModeName) ?? null,
        [catalog, selectedModeName],
    );
    const selectedScope = selectedAgent?.mode_scopes[selectedModeName] ?? null;
    const matchingCandidate = selectedAgent && promptCandidateMatches(candidate, selectedAgent.prompt_name)
        ? candidate
        : null;
    const compareProduction = compareProductionOverride ?? Boolean(
        matchingCandidate?.compareProduction && selectedAgent?.latest_successful_run_id,
    );
    const modelConfigReady = Boolean(
        smartModel?.credentialStored
        && fastModel?.credentialStored
        && getApiConfigForRequest(),
    );
    const canRun = Boolean(
        catalog?.runs_enabled
        && selectedAgent
        && selectedMode
        && modelConfigReady
        && !submitting,
    );
    const catalogCaseCount = useMemo(
        () => catalog?.agents.reduce((total, agent) => total + agent.case_count, 0) ?? 0,
        [catalog],
    );
    const quickLaunchHint = !catalog?.runs_enabled
        ? '服务端尚未启用真实评测'
        : !modelConfigReady
            ? '先完成 Smart / Fast 模型设置即可运行'
            : selectedModeName !== 'quick'
                ? '当前是完整检查模式，请在下方确认配置后运行'
                : `所选 Agent 冒烟将运行 1 个稳定案例；全 Agent 冒烟将运行 ${catalog?.agents.length ?? 0} 个案例`;

    /** Queues one quick smoke run per allowlisted Agent without exposing credentials. */
    async function startAllAgentsQuickSmoke(): Promise<void> {
        if (!catalog || selectedModeName !== 'quick') {
            toast.error('全 Agent 冒烟仅支持快速冒烟模式');
            return;
        }
        const apiConfig = getApiConfigForRequest();
        if (!apiConfig) {
            toast.error('请先在模型设置中配置 Smart 与 Fast 通道');
            return;
        }

        setSubmitting(true);
        try {
            const result = await evaluationApi.allAgentsQuickRun({ api_config: apiConfig }, createIdempotencyKey());
            if (result.failures.length) {
                toast.warning(`已启动 ${result.runs.length} 个 Agent 冒烟`, {
                    description: `${result.failures.length} 个 Agent 未能启动，请查看运行列表后重试`,
                });
            } else {
                toast.success(`已启动全部 ${result.runs.length} 个 Agent 冒烟`, {
                    description: '每个 Agent 运行 1 个稳定选择的代表案例',
                });
            }
            await onRefresh();
        } catch (error) {
            toast.error(error instanceof Error ? error.message : '全 Agent 冒烟启动失败');
        } finally {
            setSubmitting(false);
        }
    }

    /** Changes the Agent selection and clears an incompatible baseline comparison. */
    function selectAgent(agent: EvaluationCatalogAgent): void {
        setSelectedAgentName(agent.name);
        setCompareProductionOverride(false);
    }

    /** Starts a server-owned preset using the existing model settings without exposing credentials. */
    async function startEvaluation(): Promise<void> {
        if (!selectedAgent || !selectedMode) {
            toast.error('请选择 Agent 和评测模式');
            return;
        }
        const apiConfig = getApiConfigForRequest();
        if (!apiConfig) {
            toast.error('请先在模型设置中配置 Smart 与 Fast 通道');
            return;
        }

        setSubmitting(true);
        try {
            const run = await evaluationApi.quickRun({
                agent_name: selectedAgent.name,
                mode: selectedMode.name,
                api_config: apiConfig,
                prompt_name: matchingCandidate?.name ?? selectedAgent.prompt_name,
                prompt_version: matchingCandidate?.version ?? selectedAgent.prompt_version,
                compare_production: compareProduction && Boolean(selectedAgent.latest_successful_run_id),
            }, createIdempotencyKey());
            if (matchingCandidate) {
                localStorage.removeItem('evaluationPromptCandidate');
                setSelectedAgentName(selectedAgent.name);
                setCandidate(null);
            }
            toast.success(`${selectedAgent.label}评测已启动`, {
                description: `运行 ${shortId(run.id)} 已进入可恢复任务队列`,
            });
            await onRefresh();
        } catch (error) {
            toast.error(error instanceof Error ? error.message : '一键评测启动失败');
        } finally {
            setSubmitting(false);
        }
    }

    if (!catalog) {
        return <div className="rounded-2xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-500">
            {loading ? '正在加载一键评测目录…' : '一键评测目录暂不可用，请刷新重试。'}
        </div>;
    }

    return <div className="space-y-5">
        <section className="rounded-2xl border border-teal-100 bg-gradient-to-br from-white via-white to-teal-50/70 p-5 shadow-sm">
            <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
                <div>
                    <div className="flex items-center gap-2 text-sm font-semibold text-teal-800">
                        <Sparkles className="h-4 w-4" /> 一键评测
                    </div>
                    <h3 className="mt-2 text-lg font-semibold text-slate-900">只选 Agent 和评测强度，其余由系统准备</h3>
                    <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">
                        自动读取模型设置，创建并锁定内置 Dataset Version，复用内置 Suite 与 Rubric，然后进入可恢复 AgentRun。
                    </p>
                </div>
                <div className="flex flex-col items-stretch gap-2 sm:items-end">
                    <ContextualHelpIcon id="credential-boundary" label="凭据安全边界">
                        API Key 不在页面展示；只随本次请求发送，并由后端加密进入任务载荷。
                    </ContextualHelpIcon>
                    {selectedModeName === 'quick' && <Button
                        size="lg"
                        className="min-w-52 bg-teal-600 hover:bg-teal-700"
                        disabled={!canRun}
                        onClick={() => void startEvaluation()}
                    >
                        <Play className="mr-2 h-4 w-4" />
                        {submitting ? '正在启动…' : '一键运行快速冒烟'}
                    </Button>}
                </div>
            </div>
            <div className="mt-4 flex flex-col gap-3 rounded-xl border border-teal-100 bg-white/80 p-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex flex-wrap items-center gap-2 text-sm">
                    <Badge className="bg-teal-700 hover:bg-teal-700">{catalog.agents.length} 个可评测 Agent</Badge>
                    <Badge variant="secondary">共 {catalogCaseCount} 条内置案例</Badge>
                </div>
                <p className="text-xs text-slate-600">{quickLaunchHint}</p>
            </div>
        </section>

        {!catalog.runs_enabled && <Notice tone="warning" text="服务端尚未启用 EVALUATION_RUNS_ENABLED；可以查看目录和历史结果，但暂不能启动真实评测。" />}
        {!modelConfigReady && <Notice tone="warning" text="尚未配置完整的 Smart / Fast 模型通道。请先前往“模型设置”完成配置，一键评测会自动读取。" />}
        {matchingCandidate && <Notice tone="info" text={`已识别 Prompt 候选：${matchingCandidate.name} v${matchingCandidate.version}，运行时会自动带入。`} />}

        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <SectionHeading step="1" title="选择 Agent" description="这些入口对应真实生产 Agent，不需要填写内部名称。" />
            <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {catalog.agents.map(agent => {
                    const active = agent.name === effectiveAgentName;
                    return <button
                        key={agent.name}
                        type="button"
                        onClick={() => selectAgent(agent)}
                        className={`rounded-xl border p-4 text-left transition ${active
                            ? 'border-teal-500 bg-teal-50 ring-2 ring-teal-100'
                            : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50'}`}
                    >
                        <div className="flex items-start justify-between gap-3">
                            <div className={`flex h-9 w-9 items-center justify-center rounded-lg ${active ? 'bg-teal-600 text-white' : 'bg-slate-100 text-slate-600'}`}>
                                <Bot className="h-4 w-4" />
                            </div>
                            {active && <CheckCircle2 className="h-5 w-5 text-teal-600" />}
                        </div>
                        <div className="mt-3 font-medium text-slate-900">{agent.label}</div>
                        <p className="mt-1 min-h-10 text-xs leading-5 text-slate-500">{agent.description}</p>
                        <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-slate-500">
                            <span className="rounded bg-slate-100 px-2 py-1">冒烟 {agent.mode_scopes.quick.case_count} · 回归 {agent.mode_scopes.standard.case_count} · 发布 {agent.mode_scopes.release.case_count}</span>
                            <span className="rounded bg-slate-100 px-2 py-1">{agent.prompt_name} v{agent.prompt_version}</span>
                        </div>
                    </button>;
                })}
            </div>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <SectionHeading step="2" title="选择评测强度" description="预算、并发、重复次数、Judge 与人工抽检均由服务端预设并限制。" />
            <div className="mt-4 grid gap-3 lg:grid-cols-3">
                {catalog.modes.map(mode => <ModeCard
                    key={mode.name}
                    mode={mode}
                    active={mode.name === selectedModeName}
                    onSelect={setSelectedModeName}
                />)}
            </div>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <SectionHeading step="3" title="确认并运行" description="这里只展示自动采用的配置摘要，不展示 API Key 或完整地址。" />
            <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                <SummaryItem icon={<Gauge className="h-4 w-4" />} label="Smart 通道" value={smartModel ? `${smartModel.name} · ${smartModel.model}` : '未配置'} />
                <SummaryItem icon={<Clock3 className="h-4 w-4" />} label="Fast 通道" value={fastModel ? `${fastModel.name} · ${fastModel.model}` : '未配置'} />
                <SummaryItem icon={<Database className="h-4 w-4" />} label="Dataset / Suite" value={selectedScope ? `${selectedScope.dataset_name}:${selectedScope.dataset_version}` : '-'} />
                <SummaryItem icon={<Scale className="h-4 w-4" />} label="Rubric / Prompt" value={selectedScope && selectedAgent ? `${selectedScope.rubric_version} · ${matchingCandidate?.version ?? selectedAgent.prompt_version}` : '-'} />
            </div>
            {selectedScope && selectedModeName !== 'quick' && <div className="mt-3 rounded-xl border border-indigo-100 bg-indigo-50/50 p-3 text-xs text-slate-600">
                <div className="font-medium text-slate-800">本次运行范围</div>
                <p className="mt-1">{formatEvaluationScopeSummary(selectedScope)}</p>
            </div>}

            <div className="mt-4 flex flex-col gap-4 rounded-xl border border-slate-200 bg-slate-50 p-4 lg:flex-row lg:items-center lg:justify-between">
                <div className="flex items-center gap-3">
                    <Switch
                        checked={compareProduction}
                        onCheckedChange={setCompareProductionOverride}
                        disabled={!selectedAgent?.latest_successful_run_id}
                        aria-label="与最近成功运行比较"
                    />
                    <div>
                        <div className="text-sm font-medium text-slate-800">与最近成功运行比较</div>
                        <p className="text-xs text-slate-500">
                            {selectedAgent?.latest_successful_run_id
                                ? `自动使用 ${shortId(selectedAgent.latest_successful_run_id)} 作为基线`
                                : '该 Agent 暂无成功基线，首次运行后即可比较'}
                        </p>
                    </div>
                </div>
                <div className="flex flex-wrap gap-3">
                    {selectedModeName === 'quick' && <Button
                        size="lg"
                        variant="outline"
                        className="min-w-52 border-teal-200 text-teal-700 hover:bg-teal-50"
                        disabled={!canRun}
                        onClick={() => void startAllAgentsQuickSmoke()}
                    >
                        <Play className="mr-2 h-4 w-4" />
                        {submitting ? '正在启动…' : `一键全 Agent 冒烟（${catalog.agents.length} 个案例）`}
                    </Button>}
                    <Button
                        size="lg"
                        className="min-w-40 bg-teal-600 hover:bg-teal-700"
                        disabled={!canRun}
                        onClick={() => void startEvaluation()}
                    >
                        <Play className="mr-2 h-4 w-4" />
                        {submitting ? '正在启动…' : `运行所选${selectedMode?.label ?? '评测'}`}
                    </Button>
                </div>
            </div>
        </section>

        <RecentEvaluationResults
            catalog={catalog}
            runs={runs}
            selectedAgentName={effectiveAgentName}
            loading={loading}
            onRefresh={onRefresh}
            onOpenRun={onOpenRun}
        />
    </div>;
}

/** Renders a numbered section heading for the guided one-click flow. */
function SectionHeading({ step, title, description }: { step: string; title: string; description: string }) {
    return <div className="flex items-start gap-3">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-900 text-xs font-semibold text-white">{step}</div>
        <div><h3 className="font-semibold text-slate-900">{title}</h3><p className="mt-1 text-xs text-slate-500">{description}</p></div>
    </div>;
}

/** Renders one server-owned mode preset without allowing low-level overrides. */
function ModeCard({
    mode,
    active,
    onSelect,
}: {
    mode: EvaluationQuickMode;
    active: boolean;
    onSelect: (name: EvaluationQuickModeName) => void;
}) {
    return <button
        type="button"
        onClick={() => onSelect(mode.name)}
        className={`rounded-xl border p-4 text-left transition ${active
            ? 'border-indigo-500 bg-indigo-50 ring-2 ring-indigo-100'
            : 'border-slate-200 hover:border-slate-300 hover:bg-slate-50'}`}
    >
        <div className="flex items-center justify-between"><span className="font-medium text-slate-900">{mode.label}</span>{active && <CheckCircle2 className="h-5 w-5 text-indigo-600" />}</div>
        <p className="mt-2 min-h-10 text-xs leading-5 text-slate-500">{mode.description}</p>
        <div className="mt-3 grid grid-cols-2 gap-2 text-[11px] text-slate-600">
            <span className="rounded bg-white px-2 py-1"><Coins className="mr-1 inline h-3 w-3" />预算 ${mode.max_budget_usd}</span>
            <span className="rounded bg-white px-2 py-1"><Gauge className="mr-1 inline h-3 w-3" />并发 {mode.max_concurrency}</span>
            <span className="rounded bg-white px-2 py-1">{mode.max_cases == null ? '完整数据集' : `最多 ${mode.max_cases} 案例`}</span>
            <span className="rounded bg-white px-2 py-1">{mode.include_judges ? '启用 Judge' : '规则评测'}</span>
        </div>
    </button>;
}

/** Renders a credential-safe configuration summary item. */
function SummaryItem({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
    return <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
        <div className="flex items-center gap-2 text-xs text-slate-500">{icon}{label}</div>
        <div className="mt-2 truncate text-sm font-medium text-slate-800" title={value}>{value}</div>
    </div>;
}

/** Renders a compact operational notice with stable visual severity. */
function Notice({ tone, text }: { tone: 'warning' | 'info'; text: string }) {
    const warning = tone === 'warning';
    return <div className={`flex items-start gap-3 rounded-xl border px-4 py-3 text-sm ${warning ? 'border-amber-200 bg-amber-50 text-amber-800' : 'border-blue-200 bg-blue-50 text-blue-800'}`}>
        {warning ? <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" /> : <Sparkles className="mt-0.5 h-4 w-4 shrink-0" />}
        <span>{text}</span>
    </div>;
}

/** Creates a retry-safe browser request key without persisting credentials or payload data. */
function createIdempotencyKey(): string {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
    return `evaluation-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/** Shortens opaque identifiers while retaining enough context for visual recognition. */
function shortId(value: string): string {
    return value.length > 18 ? `${value.slice(0, 9)}…${value.slice(-6)}` : value;
}
