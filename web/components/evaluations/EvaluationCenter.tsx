'use client';

import { useCallback, useEffect, useState } from 'react';
import { ArrowLeft, RefreshCw, ShieldCheck, SlidersHorizontal } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
    evaluationApi,
    type EvaluationCalibration,
    type EvaluationCaseRun,
    type EvaluationCatalog,
    type EvaluationDataset,
    type EvaluationGatePolicy,
    type EvaluationOverview,
    type EvaluationRegression,
    type EvaluationRun,
    type EvaluationSuite,
    type EvaluationTrendPoint,
} from '@/lib/api/evaluations';
import { EvaluationOverviewPanel } from './EvaluationOverviewPanel';
import { EvaluationRunsPanel } from './EvaluationRunsPanel';
import { AnnotationsPanel, CalibrationPanel, DatasetsPanel, GatesPanel } from './EvaluationGovernancePanels';
import { QuickEvaluationPanel } from './QuickEvaluationPanel';

/** Coordinates one-click evaluation by default and keeps six governance surfaces in Advanced Mode. */
export function EvaluationCenter() {
    const [loading, setLoading] = useState(true);
    const [advancedMode, setAdvancedMode] = useState(false);
    const [activeTab, setActiveTab] = useState('overview');
    const [focusRunId, setFocusRunId] = useState<string | null>(null);
    const [catalog, setCatalog] = useState<EvaluationCatalog | null>(null);
    const [overview, setOverview] = useState<EvaluationOverview | null>(null);
    const [trends, setTrends] = useState<EvaluationTrendPoint[]>([]);
    const [regressions, setRegressions] = useState<EvaluationRegression[]>([]);
    const [datasets, setDatasets] = useState<EvaluationDataset[]>([]);
    const [suites, setSuites] = useState<EvaluationSuite[]>([]);
    const [runs, setRuns] = useState<EvaluationRun[]>([]);
    const [queue, setQueue] = useState<Array<EvaluationCaseRun & { agent_name: string }>>([]);
    const [calibrations, setCalibrations] = useState<EvaluationCalibration[]>([]);
    const [gates, setGates] = useState<EvaluationGatePolicy[]>([]);

    /** Refreshes one-click and governance data while preserving owner-scoped backend boundaries. */
    const refresh = useCallback(async () => {
        setLoading(true);
        try {
            const [
                catalogResult,
                overviewResult,
                trendResult,
                regressionResult,
                datasetResult,
                suiteResult,
                runResult,
                queueResult,
                calibrationResult,
                gateResult,
            ] = await Promise.all([
                evaluationApi.catalog(),
                evaluationApi.overview(),
                evaluationApi.trends(),
                evaluationApi.regressions(),
                evaluationApi.datasets(),
                evaluationApi.suites(),
                evaluationApi.runs(),
                evaluationApi.annotationQueue(),
                evaluationApi.calibrations(),
                evaluationApi.gates(),
            ]);
            setCatalog(catalogResult);
            setOverview(overviewResult);
            setTrends(trendResult.items);
            setRegressions(regressionResult.items);
            setDatasets(datasetResult.items);
            setSuites(suiteResult.items);
            setRuns(runResult.items);
            setQueue(queueResult.items);
            setCalibrations(calibrationResult.items);
            setGates(gateResult.items);
        } catch (error) {
            toast.error(error instanceof Error ? error.message : '评测中心加载失败');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        const timer = window.setTimeout(() => void refresh(), 0);
        return () => window.clearTimeout(timer);
    }, [refresh]);

    /** Opens a run in Advanced Mode so low-level evidence and governance remain available on demand. */
    function openRun(runId: string): void {
        setFocusRunId(runId);
        setActiveTab('runs');
        setAdvancedMode(true);
    }

    /** Queues failed cases for human review, then opens the Advanced annotation workspace. */
    async function requestReview(runId: string): Promise<void> {
        try {
            const result = await evaluationApi.requestReview(runId);
            toast.success(`已将 ${result.queued_count} 个失败案例加入人工复核`);
            await refresh();
            setActiveTab('annotations');
            setAdvancedMode(true);
        } catch (error) {
            toast.error(error instanceof Error ? error.message : '发起人工复核失败');
        }
    }

    /** Returns to the guided one-click surface without discarding loaded governance state. */
    function leaveAdvancedMode(): void {
        setAdvancedMode(false);
        setFocusRunId(null);
    }

    return <div className="h-full overflow-auto bg-slate-50/70 p-4 sm:p-6">
        <div className="mx-auto max-w-[1500px]">
            <header className="mb-5 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                <div className="flex flex-col justify-between gap-4 md:flex-row md:items-center">
                    <div className="flex gap-3">
                        <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-teal-50 text-teal-700">
                            <ShieldCheck className="h-5 w-5" />
                        </div>
                        <div>
                            <h2 className="text-xl font-semibold text-slate-900">Agent 评测中心</h2>
                            <p className="mt-1 text-sm text-slate-500">运行评测、观察质量、人工标注并校准 Agent 与 Judge</p>
                            <p className="mt-1 text-[11px] text-slate-400">PostgreSQL 保存生命周期事实；Langfuse 只承载 Trace 与 Score 镜像。</p>
                        </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        {advancedMode
                            ? <Button variant="outline" onClick={leaveAdvancedMode}>
                                <ArrowLeft className="mr-2 h-4 w-4" />返回一键评测
                            </Button>
                            : <Button variant="outline" onClick={() => setAdvancedMode(true)}>
                                <SlidersHorizontal className="mr-2 h-4 w-4" />高级模式
                            </Button>}
                        <Button variant="outline" onClick={() => void refresh()} disabled={loading}>
                            <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />刷新全部
                        </Button>
                    </div>
                </div>
            </header>

            {!advancedMode
                ? <QuickEvaluationPanel
                    catalog={catalog}
                    runs={runs}
                    loading={loading}
                    onRefresh={refresh}
                    onOpenRun={openRun}
                />
                : <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-4">
                    <TabsList className="h-auto flex-wrap justify-start">
                        <TabsTrigger value="overview">总览</TabsTrigger>
                        <TabsTrigger value="runs">评测运行</TabsTrigger>
                        <TabsTrigger value="datasets">数据集</TabsTrigger>
                        <TabsTrigger value="annotations">人工标注</TabsTrigger>
                        <TabsTrigger value="calibration">Judge 校准</TabsTrigger>
                        <TabsTrigger value="gates">发布门禁</TabsTrigger>
                    </TabsList>
                    <TabsContent value="overview">
                        <EvaluationOverviewPanel overview={overview} trends={trends} regressions={regressions} onOpenRun={openRun} onRequestReview={requestReview} />
                    </TabsContent>
                    <TabsContent value="runs">
                        <EvaluationRunsPanel
                            runs={runs}
                            suites={suites}
                            focusRunId={focusRunId}
                            onRefresh={refresh}
                            onOpenAnnotations={() => setActiveTab('annotations')}
                        />
                    </TabsContent>
                    <TabsContent value="datasets"><DatasetsPanel datasets={datasets} suites={suites} onRefresh={refresh} /></TabsContent>
                    <TabsContent value="annotations"><AnnotationsPanel queue={queue} onRefresh={refresh} /></TabsContent>
                    <TabsContent value="calibration"><CalibrationPanel calibrations={calibrations} onRefresh={refresh} /></TabsContent>
                    <TabsContent value="gates"><GatesPanel gates={gates} runs={runs} onRefresh={refresh} /></TabsContent>
                </Tabs>}
        </div>
    </div>;
}
