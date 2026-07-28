'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertCircle, Brain, CheckCircle2, Loader2, RefreshCw, Target, Zap } from 'lucide-react';
import { getSessionProfile, type AbilityProfile } from '@/lib/api/profile';
import { getSessionWeaknessReport, type WeaknessReport } from '@/lib/api/weakness';
import {
    createInterviewReportRun,
    listAgentRuns,
    pollAgentRun,
    type AgentRun,
} from '@/lib/api/agentRuns';
import { getRequestApiConfig } from '@/store/interviewFacade';
import { AbilityRadarChart } from './RadarChart';
import { SkillTags } from './SkillTags';
import { WeaknessMap } from './WeaknessMap';
import { Button } from './ui/button';
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
} from './ui/dialog';
import { cn } from '@/lib/utils';

interface Props {
    sessionId: string;
    open: boolean;
    onOpenChange: (open: boolean) => void;
    defaultTab?: TabType;
}

type TabType = 'profile' | 'weakness';
const ACTIVE_RUN_STATUSES = new Set<AgentRun['status']>([
    'queued',
    'retrying',
    'running',
    'cancel_requested',
]);

const PROFILE_DIMENSIONS: Array<{
    key: keyof Pick<
        AbilityProfile,
        'professional_competence' | 'execution_results' | 'logic_problem_solving' |
        'communication' | 'growth_potential' | 'collaboration'
    >;
    label: string;
}> = [
    { key: 'professional_competence', label: '专业能力' },
    { key: 'execution_results', label: '执行与结果导向' },
    { key: 'logic_problem_solving', label: '逻辑与问题解决' },
    { key: 'communication', label: '沟通表达力' },
    { key: 'growth_potential', label: '成长潜力' },
    { key: 'collaboration', label: '协作能力' },
];

/** Renders the session profile dialog UI and coordinates its typed props, local state, and approved backend interactions. */
export function SessionProfileDialog({ sessionId, open, onOpenChange, defaultTab = 'profile' }: Props) {
    const [activeTab, setActiveTab] = useState<TabType>(defaultTab);
    const [profile, setProfile] = useState<AbilityProfile | null>(null);
    const [weakness, setWeakness] = useState<WeaknessReport | null>(null);
    const [loading, setLoading] = useState(true);
    const [submitting, setSubmitting] = useState(false);
    const [reportRun, setReportRun] = useState<AgentRun | null>(null);
    const [error, setError] = useState<string | null>(null);
    const pollAbortRef = useRef<AbortController | null>(null);

    /** Reload both persisted report artifacts without creating another model task. */
    const loadArtifacts = useCallback(async () => {
        const [profileResponse, weaknessResponse] = await Promise.all([
            getSessionProfile(sessionId),
            getSessionWeaknessReport(sessionId),
        ]);
        setProfile(profileResponse.success && profileResponse.profile ? profileResponse.profile : null);
        setWeakness(weaknessResponse.success && weaknessResponse.report ? weaknessResponse.report : null);
    }, [sessionId]);

    /** Follow one recoverable report task and reload both tabs after its terminal state. */
    const monitorRun = useCallback(async (runId: string, signal: AbortSignal) => {
        try {
            const completed = await pollAgentRun(runId, setReportRun, signal);
            setReportRun(completed);
            if (completed.status === 'succeeded') {
                await loadArtifacts();
                setError(null);
            } else {
                setError(completed.error_message || '面试报告任务执行失败');
            }
        } catch (cause) {
            if (cause instanceof Error && cause.name === 'AbortError') return;
            setError(cause instanceof Error ? cause.message : '读取报告任务状态失败');
        }
    }, [loadArtifacts]);

    /** Create one shared report task for both tabs; tab switches reuse this same run. */
    const handleGenerate = useCallback(async () => {
        if (reportRun && ACTIVE_RUN_STATUSES.has(reportRun.status)) return;
        const apiConfig = getRequestApiConfig();
        if (!apiConfig) {
            setError('请先在设置中配置 API Key');
            return;
        }

        setSubmitting(true);
        setError(null);
        pollAbortRef.current?.abort();
        const controller = new AbortController();
        pollAbortRef.current = controller;
        try {
            const created = await createInterviewReportRun({
                session_id: sessionId,
                api_config: apiConfig,
            });
            if ('run_id' in created) {
                setReportRun(created);
                await monitorRun(created.run_id, controller.signal);
            } else {
                await loadArtifacts();
            }
        } catch (cause) {
            setError(cause instanceof Error ? cause.message : '生成面试报告失败');
        } finally {
            if (!controller.signal.aborted) setSubmitting(false);
        }
    }, [loadArtifacts, monitorRun, reportRun, sessionId]);

    useEffect(() => {
        if (!open || !sessionId) return;

        pollAbortRef.current?.abort();
        const controller = new AbortController();
        pollAbortRef.current = controller;

        const timer = window.setTimeout(() => {
            setActiveTab(defaultTab);
            setLoading(true);
            setSubmitting(false);
            setError(null);
            void Promise.all([
                loadArtifacts(),
                listAgentRuns({
                    taskType: 'interview_report',
                    sessionId,
                    limit: 1,
                }),
            ]).then(([, runsResponse]) => {
                if (controller.signal.aborted) return;
                const latestRun = runsResponse.runs[0] || null;
                setReportRun(latestRun);
                setLoading(false);
                if (latestRun && ACTIVE_RUN_STATUSES.has(latestRun.status)) {
                    void monitorRun(latestRun.run_id, controller.signal);
                } else if (latestRun?.status === 'failed') {
                    setError(latestRun.error_message || '面试报告任务执行失败');
                }
            }).catch((cause) => {
                if (controller.signal.aborted) return;
                setLoading(false);
                setError(cause instanceof Error ? cause.message : '加载面试报告失败');
            });
        }, 0);

        return () => {
            window.clearTimeout(timer);
            controller.abort();
        };
    }, [defaultTab, loadArtifacts, monitorRun, open, sessionId]);

    const generating = submitting || Boolean(
        reportRun && ACTIVE_RUN_STATUSES.has(reportRun.status),
    );
    const currentStep = reportRun?.plan.find(step => step.status === 'running');

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                        <Brain className="w-5 h-5 text-teal-600" />
                        本轮面试评估
                    </DialogTitle>
                </DialogHeader>

                {/* Tab 切换 */}
                <div className="flex gap-1 bg-gray-100 rounded-lg p-1">
                    <button
                        onClick={() => setActiveTab('profile')}
                        className={cn(
                            'flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-all',
                            activeTab === 'profile'
                                ? 'bg-white text-gray-900 shadow-sm'
                                : 'text-gray-500 hover:text-gray-700'
                        )}
                    >
                        <Brain className="w-4 h-4" />
                        能力画像
                    </button>
                    <button
                        onClick={() => setActiveTab('weakness')}
                        className={cn(
                            'flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-all',
                            activeTab === 'weakness'
                                ? 'bg-white text-gray-900 shadow-sm'
                                : 'text-gray-500 hover:text-gray-700'
                        )}
                    >
                        <Target className="w-4 h-4" />
                        短板地图
                    </button>
                </div>

                {reportRun && (generating || reportRun.status === 'failed') && (
                    <div className={cn(
                        'rounded-xl border p-4',
                        reportRun.status === 'failed'
                            ? 'border-red-200 bg-red-50'
                            : 'border-teal-200 bg-teal-50',
                    )}>
                        <div className="flex items-start gap-3">
                            {reportRun.status === 'failed' ? (
                                <AlertCircle className="mt-0.5 h-5 w-5 flex-shrink-0 text-red-600" />
                            ) : (
                                <Loader2 className="mt-0.5 h-5 w-5 flex-shrink-0 animate-spin text-teal-600" />
                            )}
                            <div className="min-w-0 flex-1">
                                <p className="text-sm font-semibold text-gray-900">
                                    {reportRun.status === 'failed'
                                        ? '报告生成失败'
                                        : currentStep?.title || '正在准备面试报告'}
                                </p>
                                {reportRun.status === 'failed' && (
                                    <p className="mt-1 text-xs leading-5 text-red-700">
                                        {error || reportRun.error_message || '请稍后重新生成'}
                                    </p>
                                )}
                                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                                    {reportRun.plan.map(step => (
                                        <div key={step.id} className="flex items-center gap-2 text-xs text-gray-600">
                                            {step.status === 'completed' ? (
                                                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />
                                            ) : step.status === 'running' ? (
                                                <Loader2 className="h-3.5 w-3.5 animate-spin text-teal-600" />
                                            ) : step.status === 'failed' ? (
                                                <AlertCircle className="h-3.5 w-3.5 text-red-600" />
                                            ) : (
                                                <span className="h-3.5 w-3.5 rounded-full border border-gray-300" />
                                            )}
                                            <span>{step.title}</span>
                                        </div>
                                    ))}
                                </div>
                                {reportRun.status === 'failed' && (
                                    <Button
                                        onClick={() => void handleGenerate()}
                                        disabled={submitting}
                                        variant="outline"
                                        size="sm"
                                        className="mt-3"
                                    >
                                        <RefreshCw className="h-4 w-4" />
                                        重新生成完整报告
                                    </Button>
                                )}
                            </div>
                        </div>
                    </div>
                )}

                {error && reportRun?.status !== 'failed' && (
                    <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                        <AlertCircle className="h-4 w-4 flex-shrink-0" />
                        {error}
                    </div>
                )}

                {/* 能力画像 Tab */}
                <div className={activeTab === 'profile' ? '' : 'hidden'}>
                    <>
                        {/* 加载状态 */}
                        {loading && (
                            <div className="flex flex-col items-center justify-center py-20">
                                <Loader2 className="w-8 h-8 text-teal-600 animate-spin mb-4" />
                                <p className="text-sm text-gray-500">加载中...</p>
                            </div>
                        )}

                        {/* 生成中状态 */}
                        {!loading && !profile && generating && (
                            <div className="flex flex-col items-center justify-center py-20 px-6">
                                <div className="w-16 h-16 bg-teal-50 rounded-full flex items-center justify-center mb-4">
                                    <Loader2 className="w-8 h-8 text-teal-600 animate-spin" />
                                </div>
                                <h3 className="text-lg font-semibold text-gray-900 mb-2">画像生成中</h3>
                                <p className="text-sm text-gray-500 text-center mb-6 max-w-sm">
                                    当前任务会同时生成能力画像与短板地图，切换标签不会重新开始。
                                </p>
                            </div>
                        )}

                        {!loading && !profile && !generating && (
                            <div className="flex flex-col items-center justify-center py-20 px-6">
                                <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-teal-50">
                                    <Brain className="h-8 w-8 text-teal-600" />
                                </div>
                                <h3 className="mb-2 text-lg font-semibold text-gray-900">暂无能力画像</h3>
                                <p className="mb-6 max-w-sm text-center text-sm text-gray-500">
                                    生成一次完整报告即可同时获得能力画像和短板地图。
                                </p>
                                <Button
                                    onClick={() => void handleGenerate()}
                                    disabled={submitting}
                                    className="gap-2 bg-teal-600 text-white hover:bg-teal-700"
                                >
                                    {submitting ? (
                                        <Loader2 className="h-4 w-4 animate-spin" />
                                    ) : (
                                        <Zap className="h-4 w-4" />
                                    )}
                                    生成完整报告
                                </Button>
                            </div>
                        )}

                        {/* 有数据 - 显示画像 */}
                        {!loading && profile && (
                            <div className="space-y-6">
                                <div className="flex justify-end">
                                    <Button
                                        onClick={() => void handleGenerate()}
                                        disabled={generating}
                                        variant="outline"
                                        size="sm"
                                        className="gap-2"
                                    >
                                        {generating ? (
                                            <Loader2 className="h-4 w-4 animate-spin" />
                                        ) : (
                                            <RefreshCw className="h-4 w-4" />
                                        )}
                                        重新生成完整报告
                                    </Button>
                                </div>
                                {/* 雷达图 */}
                                <div className="bg-gray-50 rounded-xl p-6">
                                    <h3 className="text-base font-semibold text-gray-900 mb-4">能力雷达图</h3>
                                    <AbilityRadarChart data={profile} />
                                </div>

                                {/* 技能标签 */}
                                {profile.skill_tags && profile.skill_tags.length > 0 && (
                                    <div className="bg-blue-50 rounded-xl p-6">
                                        <SkillTags tags={profile.skill_tags} />
                                    </div>
                                )}

                                {/* 综合评价 */}
                                {profile.overall_assessment && (
                                    <div className="bg-purple-50 rounded-xl p-6">
                                        <h3 className="text-base font-semibold text-gray-900 mb-3">综合评价</h3>
                                        <p className="text-sm text-gray-700 leading-relaxed">
                                            {profile.overall_assessment}
                                        </p>
                                    </div>
                                )}

                                {/* 优势和不足 */}
                                {(profile.key_strengths && profile.key_strengths.length > 0 ||
                                    profile.key_weaknesses && profile.key_weaknesses.length > 0) && (
                                        <div className="grid grid-cols-2 gap-4">
                                            {profile.key_strengths && profile.key_strengths.length > 0 && (
                                                <div className="bg-emerald-50 rounded-xl p-6">
                                                    <h3 className="text-base font-semibold text-gray-900 mb-3">主要优势</h3>
                                                    <ul className="space-y-2">
                                                        {profile.key_strengths.map((strength, index) => (
                                                            <li key={index} className="text-sm text-gray-700 flex items-start gap-2">
                                                                <span className="text-teal-600 mt-0.5">✓</span>
                                                                <span>{strength}</span>
                                                            </li>
                                                        ))}
                                                    </ul>
                                                </div>
                                            )}
                                            {profile.key_weaknesses && profile.key_weaknesses.length > 0 && (
                                                <div className="bg-teal-50 rounded-xl p-6">
                                                    <h3 className="text-base font-semibold text-gray-900 mb-3">待提升项</h3>
                                                    <ul className="space-y-2">
                                                        {profile.key_weaknesses.map((weakness, index) => (
                                                            <li key={index} className="text-sm text-gray-700 flex items-start gap-2">
                                                                <span className="text-amber-600 mt-0.5">△</span>
                                                                <span>{weakness}</span>
                                                            </li>
                                                        ))}
                                                    </ul>
                                                </div>
                                            )}
                                        </div>
                                    )}

                                {/* 维度评分详情 */}
                                {profile && (
                                    <div className="bg-white rounded-xl border border-gray-200 p-4">
                                        <h3 className="text-base font-semibold text-gray-900 mb-3">评分详情</h3>
                                        <div className="space-y-3">
                                            {PROFILE_DIMENSIONS.map(({ key, label }) => {
                                                const dim = profile[key];
                                                return (
                                                    <div key={key} className="border border-gray-100 rounded-lg p-3">
                                                        <div className="flex items-center justify-between mb-1">
                                                            <span className="text-sm font-medium text-gray-900">{label}</span>
                                                            <span className="text-sm font-bold text-teal-600">{dim.score}/10</span>
                                                        </div>
                                                        {dim.reason && (
                                                            <p className="text-xs text-blue-600">{dim.reason}</p>
                                                        )}
                                                        {dim.improvement_tip && (
                                                            <p className="text-xs text-amber-600 mt-1">🎯 {dim.improvement_tip}</p>
                                                        )}
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    </div>
                                )}
                            </div>
                        )}
                    </>
                </div>

                {/* 短板地图 Tab */}
                <div className={activeTab === 'weakness' ? '' : 'hidden'}>
                    <WeaknessMap
                        report={weakness}
                        loading={loading}
                        generating={generating}
                        onGenerate={handleGenerate}
                    />
                </div>
            </DialogContent>
        </Dialog>
    );
}
