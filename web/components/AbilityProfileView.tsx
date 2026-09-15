'use client';

import { useState, useEffect } from 'react';
import { Loader2, RefreshCw, AlertCircle, CheckCircle2, Check, Brain, Wand2, Lightbulb, Target } from 'lucide-react';
import { getOverallProfile, generateProfile, type AbilityProfile, type AbilityProfileProgress, type AbilityProfileSource } from '@/lib/api/profile';
import { normalizeAbilityGrowth, type AbilityGrowthRecord } from '@/lib/abilityGrowth';
import { AbilityRadarChart } from './RadarChart';
import { Button } from './ui/button';
import { getRequestApiConfig } from '@/store/interviewFacade';

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

function AbilityProfileProgressCard({ progress }: { progress: AbilityProfileProgress }) {
    const visibleRounds = progress.ready_to_generate
        ? progress.required_rounds
        : progress.eligible_rounds;
    const percent = Math.min(
        100,
        Math.round((visibleRounds / Math.max(1, progress.required_rounds)) * 100),
    );
    const isReady = progress.ready_to_generate;
    const degradedRounds = progress.degraded_round_indexes.join('、');
    const statusText = isReady
        ? `已有 ${progress.company_profile_count} 份公司三轮总画像，可以生成综合能力画像。`
        : progress.blocker === 'degraded_round_reports'
            ? `已完成 ${progress.completed_rounds} 轮面试，但当前系列第 ${degradedRounds || '部分'} 轮报告未形成有效评分。`
            : progress.blocker === 'company_profile_pending'
                ? '三轮有效评分已经齐全，但公司三轮总画像尚未生成。'
                : `已完成 ${progress.completed_rounds} 轮面试；需要在同一公司系列内完成三轮并生成有效评分。`;
    const actionText = progress.blocker === 'degraded_round_reports'
        ? `请在历史面试中重新生成第 ${degradedRounds || '对应'} 轮深度报告，最后重新生成第 3 轮报告。`
        : progress.blocker === 'company_profile_pending'
            ? '请在历史面试中重新生成第 3 轮深度报告。'
            : null;

    return (
        <section
            className={`rounded-2xl border p-5 ${isReady ? 'border-teal-200 bg-teal-50/70' : 'border-amber-200 bg-amber-50/70'}`}
            aria-label="综合能力画像生成进度"
        >
            <div className="flex items-start justify-between gap-4">
                <div className="flex items-start gap-3">
                    <div className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${isReady ? 'bg-teal-100 text-teal-700' : 'bg-amber-100 text-amber-700'}`}>
                        {isReady ? <CheckCircle2 className="h-5 w-5" /> : <Target className="h-5 w-5" />}
                    </div>
                    <div>
                        <h3 className="text-sm font-semibold text-slate-900">公司三轮画像准备度</h3>
                        <p className={`mt-1 text-xs leading-5 ${isReady ? 'text-teal-700' : 'text-amber-800'}`}>
                            {statusText}
                        </p>
                    </div>
                </div>
                <span className={`shrink-0 text-sm font-bold ${isReady ? 'text-teal-700' : 'text-amber-800'}`}>
                    {visibleRounds}/{progress.required_rounds} 有效轮次
                </span>
            </div>
            <div className="mt-4" role="progressbar" aria-valuemin={0} aria-valuemax={progress.required_rounds} aria-valuenow={visibleRounds} aria-label={`已有 ${visibleRounds} 轮有效评分，目标 ${progress.required_rounds} 轮`}>
                <div className="h-2 overflow-hidden rounded-full bg-white/80">
                    <div
                        className={`h-full rounded-full transition-[width] duration-500 ${isReady ? 'bg-teal-500' : 'bg-amber-500'}`}
                        style={{ width: `${percent}%` }}
                    />
                </div>
            </div>
            <div className={`mt-2 flex justify-between gap-4 text-[11px] ${isReady ? 'text-teal-700' : 'text-amber-800'}`}>
                <span>累计完成 {progress.completed_rounds} 轮面试</span>
                <span>{isReady ? `可用公司画像 ${progress.company_profile_count} 份` : `还差 ${progress.remaining_rounds} 轮有效评分`}</span>
            </div>
            {actionText && (
                <p className="mt-3 rounded-lg bg-white/70 px-3 py-2 text-xs leading-5 text-amber-900">
                    {actionText}
                </p>
            )}
        </section>
    );
}

function applyGrowthRecord(
    record: AbilityGrowthRecord,
    setProfile: (profile: AbilityProfile | null) => void,
    setGeneratedAt: (value: string | null) => void,
    setSources: (value: AbilityProfileSource[]) => void,
    setDimensionChanges: (value: Record<string, number>) => void,
    setSampleCount: (value: number) => void,
) {
    setProfile(record.profile);
    setGeneratedAt(record.generatedAt);
    setSources(record.sources);
    setDimensionChanges(record.dimensionChanges);
    setSampleCount(record.sampleCount);
}

/** Renders the ability profile view UI and coordinates its typed props, local state, and approved backend interactions. */
export function AbilityProfileView() {
    const [profile, setProfile] = useState<AbilityProfile | null>(null);
    const [loading, setLoading] = useState(true);
    const [generating, setGenerating] = useState(false);
    const [generatedAt, setGeneratedAt] = useState<string | null>(null);
    const [sources, setSources] = useState<AbilityProfileSource[]>([]);
    const [dimensionChanges, setDimensionChanges] = useState<Record<string, number>>({});
    const [sampleCount, setSampleCount] = useState(0);
    const [progress, setProgress] = useState<AbilityProfileProgress>({
        completed_rounds: 0,
        eligible_rounds: 0,
        required_rounds: 3,
        remaining_rounds: 3,
        company_profile_count: 0,
        degraded_round_indexes: [],
        ready_to_generate: false,
        blocker: 'incomplete_series',
    });
    const [error, setError] = useState<string | null>(null);
    const [runStage, setRunStage] = useState<string | null>(null);

    useEffect(() => {
        let active = true;

        void getOverallProfile().then((response) => {
            if (!active) return;

            const growth = normalizeAbilityGrowth(response);
            applyGrowthRecord(growth, setProfile, setGeneratedAt, setSources, setDimensionChanges, setSampleCount);
            setProgress(growth.progress);
            setLoading(false);
        });

        return () => {
            active = false;
        };
    }, []);

    /** Handles generate; updates local UI state first and delegates server mutations through the approved API boundary. */
    async function handleGenerate() {
        if (!progress.ready_to_generate) return;
        setGenerating(true);
        setError(null);

        // 获取当前 API 配置
        const apiConfig = getRequestApiConfig();

        if (!apiConfig) {
            setError('请先在设置中配置 API Key');
            setGenerating(false);
            return;
        }

        const response = await generateProfile(apiConfig, (run) => {
            setRunStage(run.plan.find(step => step.status === 'running')?.title || run.stage);
        });

        if (response.success && response.profile) {
            const refreshed = normalizeAbilityGrowth(await getOverallProfile());
            applyGrowthRecord(refreshed, setProfile, setGeneratedAt, setSources, setDimensionChanges, setSampleCount);
            setProfile(refreshed.profile || response.profile);
            setGeneratedAt(refreshed.generatedAt || new Date().toISOString());
            setProgress(refreshed.progress);
        } else {
            setError(response.message || '生成失败，请稍后重试');
        }
        setGenerating(false);
        setRunStage(null);
    }

    // 加载状态
    if (loading) {
        return (
            <div className="flex flex-col items-center justify-center h-full py-20">
                <Loader2 className="w-8 h-8 text-teal-600 animate-spin mb-4" />
                <p className="text-sm text-gray-500">加载中...</p>
            </div>
        );
    }

    // 空状态 - 尚未生成画像
    if (!profile) {
        return (
            <div className="flex flex-col items-center justify-center h-full py-20 px-6">
                <div className="w-16 h-16 bg-teal-50 rounded-full flex items-center justify-center mb-4">
                    <Brain className="w-8 h-8 text-teal-600" />
                </div>
                <h3 className="text-lg font-semibold text-gray-900 mb-2">尚未生成成长档案</h3>
                <p className="text-sm text-gray-500 text-center mb-6 max-w-sm">
                    完成足够的面试轮数后，可显式生成综合能力画像并在这里持续查看来源与变化
                </p>
                <div className="w-full max-w-md mb-5">
                    <AbilityProfileProgressCard progress={progress} />
                </div>
                <Button
                    onClick={handleGenerate}
                    disabled={generating || !progress.ready_to_generate}
                    className="bg-teal-600 hover:bg-teal-700 text-white px-6 py-2 rounded-lg flex items-center gap-2 disabled:cursor-not-allowed disabled:opacity-50"
                >
                    {generating ? (
                        <>
                            <Loader2 className="w-4 h-4 animate-spin" />
                            {runStage || '生成中...'}
                        </>
                    ) : (
                        <>
                            <Wand2 className="w-4 h-4" />
                            生成成长档案
                        </>
                    )}
                </Button>
                {error && (
                    <div className="mt-4 flex items-center gap-2 text-sm text-red-600">
                        <AlertCircle className="w-4 h-4" />
                        {error}
                    </div>
                )}
            </div>
        );
    }

    // 有数据 - 显示画像
    return (
        <div className="overflow-y-auto h-full p-6 bg-slate-50/50">
            <div className="max-w-4xl mx-auto space-y-6 pb-12">
                {/* 标题和操作栏 */}
                <div className="flex items-center justify-between">
                    <div>
                        <h2 className="text-xl font-bold text-gray-900">成长档案</h2>
                        {generatedAt && (
                            <p className="text-xs text-gray-500 mt-1">
                                生成时间: {new Date(generatedAt).toLocaleString('zh-CN')}
                            </p>
                        )}
                    </div>
                    <Button
                        onClick={handleGenerate}
                        disabled={generating || !progress.ready_to_generate}
                        variant="outline"
                        size="sm"
                        className="flex items-center gap-2"
                    >
                        {generating ? (
                            <>
                                <Loader2 className="w-4 h-4 animate-spin" />
                                {runStage || '重新生成中...'}
                            </>
                        ) : (
                            <>
                                <RefreshCw className="w-4 h-4" />
                                重新生成
                            </>
                        )}
                    </Button>
                </div>

                {error && (
                    <div className="flex items-center gap-2 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
                        <AlertCircle className="w-4 h-4 flex-shrink-0" />
                        {error}
                    </div>
                )}

                <AbilityProfileProgressCard progress={progress} />

                <div className="grid gap-4 md:grid-cols-[180px_1fr]">
                    <div className="rounded-2xl border border-teal-100 bg-teal-50/70 p-5">
                        <p className="text-xs font-medium text-teal-700">画像样本</p>
                        <p className="mt-2 text-3xl font-bold text-teal-900">{sampleCount}</p>
                        <p className="mt-1 text-xs leading-5 text-teal-700">{sampleCount >= 2 ? '可比较最近两次公司画像变化' : '样本不足时不生成趋势'}</p>
                    </div>
                    <div className="rounded-2xl border border-slate-200 bg-white p-5">
                        <h3 className="text-sm font-semibold text-slate-900">最近维度变化</h3>
                        <div className="mt-3 flex flex-wrap gap-2">
                            {PROFILE_DIMENSIONS.map(({ key, label }) => {
                                const delta = dimensionChanges[key];
                                return <span key={key} className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-700">{label} {delta == null ? '—' : `${delta > 0 ? '+' : ''}${delta}`}</span>;
                            })}
                        </div>
                    </div>
                </div>

                <div className="rounded-2xl border border-slate-200 bg-white p-5">
                    <h3 className="text-sm font-semibold text-slate-900">画像来源时间线</h3>
                    {sources.length === 0 ? <p className="mt-3 text-sm text-slate-500">暂无已完成的公司级画像来源。</p> : (
                        <div className="mt-3 space-y-3">
                            {sources.map(source => (
                                <div key={source.session_id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-100 bg-slate-50 px-4 py-3">
                                    <div><p className="text-sm font-medium text-slate-900">{source.title}</p><p className="text-xs text-slate-500">会话 {source.session_id}</p></div>
                                    <span className="text-xs text-slate-500">{source.completed_at ? new Date(source.completed_at).toLocaleString('zh-CN') : '-'}</span>
                                </div>
                            ))}
                        </div>
                    )}
                </div>

                {/* 深色仪表盘区域 */}
                <div className="bg-[#0F172A] rounded-2xl border border-gray-800 p-8 relative overflow-hidden shadow-xl">
                    {/* 背景装饰 - 网格 */}
                    <div className="absolute inset-0 bg-white/5 opacity-20"></div>
                    <div className="absolute top-0 left-0 w-full h-full overflow-hidden pointer-events-none">
                        <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] bg-purple-500/10 rounded-full blur-[80px]"></div>
                        <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] bg-teal-500/10 rounded-full blur-[80px]"></div>
                    </div>

                    {/* 背景装饰 - 中间发光 */}
                    <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-64 h-64 bg-teal-500/10 rounded-full blur-3xl pointer-events-none"></div>

                    <div className="relative z-10 flex flex-col md:flex-row items-center gap-8">
                        {/* 左侧：雷达图 */}
                        <div className="flex-1 w-full max-w-md">
                            <h3 className="text-lg font-bold text-white mb-6 flex items-center gap-2">
                                <span className="w-1 h-6 bg-teal-400 rounded-full inline-block"></span>
                                能力雷达图
                            </h3>
                            <div className="bg-white/5 rounded-2xl border border-white/5 p-4 backdrop-blur-sm">
                                <AbilityRadarChart data={profile} />
                            </div>
                        </div>

                        {/* 右侧：技能标签与摘要 */}
                        <div className="flex-1 w-full flex flex-col justify-center">
                            {profile.skill_tags && profile.skill_tags.length > 0 && (
                                <div className="mb-8">
                                    <h4 className="text-sm font-medium text-gray-400 mb-3 uppercase tracking-wider">识别到的技能栈</h4>
                                    <div className="flex flex-wrap gap-2.5">
                                        {profile.skill_tags.map((tag, index) => (
                                            <span
                                                key={index}
                                                className="px-3 py-1.5 bg-white/10 text-teal-50 border border-white/10 rounded-lg text-sm font-medium hover:bg-white/20 hover:border-teal-500/30 transition-all cursor-default"
                                            >
                                                {tag}
                                            </span>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* 简短的引导文案 */}
                            <div className="bg-gradient-to-br from-teal-500/20 to-blue-600/20 rounded-xl p-5 border border-white/10">
                                <div className="flex items-start gap-3">
                                    <Lightbulb className="w-5 h-5 text-teal-400 mt-1 flex-shrink-0" />
                                    <p className="text-sm text-gray-300 leading-relaxed">
                                        基于面试表现，虽然您的经验年限较短，但在<strong className="text-teal-300">{profile.key_strengths?.[0] || '某些领域'}</strong>展现出了不错的潜力。建议重点加强<strong className="text-teal-300">{profile.key_weaknesses?.[0] || '薄弱项'}</strong>的积累。
                                    </p>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                {/* 综合评价 */}
                {profile.overall_assessment && (
                    <div className="bg-blue-50/50 rounded-2xl border border-blue-100 p-8 shadow-sm relative overflow-hidden group">
                        <h3 className="text-lg font-bold text-gray-900 mb-4 flex items-center gap-2">
                            综合评价
                        </h3>
                        <p className="text-base text-gray-700 leading-8 text-justify">
                            {profile.overall_assessment}
                        </p>
                    </div>
                )}

                {/* 优势和不足 */}
                {(profile.key_strengths && profile.key_strengths.length > 0 ||
                    profile.key_weaknesses && profile.key_weaknesses.length > 0) && (
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                            {profile.key_strengths && profile.key_strengths.length > 0 && (
                                <div className="bg-emerald-50/60 rounded-2xl border border-emerald-100 p-6 shadow-sm relative overflow-hidden h-full">
                                    <div className="absolute top-0 left-0 w-full h-1 bg-emerald-500"></div>
                                    <h3 className="text-lg font-bold text-gray-900 mb-5 flex items-center gap-2">
                                        <div className="w-8 h-8 rounded-lg bg-emerald-100 flex items-center justify-center text-emerald-600">
                                            <CheckCircle2 className="w-4 h-4" />
                                        </div>
                                        <span className="text-emerald-600">优势</span>
                                    </h3>
                                    <ul className="space-y-4">
                                        {profile.key_strengths.map((strength, index) => (
                                            <li key={index} className="flex items-start gap-3">
                                                <span className="flex-shrink-0 w-5 h-5 rounded-full bg-emerald-100 text-emerald-600 flex items-center justify-center mt-0.5">
                                                    <Check className="w-3 h-3 stroke-[3px]" />
                                                </span>
                                                <span className="text-sm text-gray-700 leading-relaxed">{strength}</span>
                                            </li>
                                        ))}
                                    </ul>
                                </div>
                            )}
                            {profile.key_weaknesses && profile.key_weaknesses.length > 0 && (
                                <div className="bg-teal-50/60 rounded-2xl border border-teal-100 p-6 shadow-sm relative overflow-hidden h-full">
                                    <div className="absolute top-0 left-0 w-full h-1 bg-teal-500"></div>
                                    <h3 className="text-lg font-bold text-gray-900 mb-5 flex items-center gap-2">
                                        <div className="w-8 h-8 rounded-lg bg-teal-100 flex items-center justify-center text-teal-600">
                                            <AlertCircle className="w-4 h-4" />
                                        </div>
                                        <span className="text-teal-600">待改进</span>
                                    </h3>
                                    <ul className="space-y-4">
                                        {profile.key_weaknesses.map((weakness, index) => (
                                            <li key={index} className="flex items-start gap-3">
                                                <span className="flex-shrink-0 w-5 h-5 rounded-full bg-teal-100 text-teal-600 flex items-center justify-center text-xs font-bold mt-0.5">!</span>
                                                <span className="text-sm text-gray-700 leading-relaxed">{weakness}</span>
                                            </li>
                                        ))}
                                    </ul>
                                </div>
                            )}
                        </div>
                    )}

                {/* 维度评分详情 */}
                {profile && (
                    <div className="bg-white rounded-2xl border border-gray-200 p-6 shadow-sm">
                        <h3 className="text-lg font-bold text-gray-900 mb-4 flex items-center gap-2">
                            <span className="w-1 h-6 bg-blue-500 rounded-full inline-block"></span>
                            评分详情
                        </h3>
                        <div className="space-y-4">
                            {PROFILE_DIMENSIONS.map(({ key, label }) => {
                                const dim = profile[key];
                                return (
                                    <div key={key} className="border border-gray-100 rounded-xl p-4 hover:bg-gray-50/50 transition-colors">
                                        <div className="flex items-center justify-between mb-2">
                                            <span className="font-medium text-gray-900">{label}</span>
                                            <span className="text-lg font-bold text-teal-600">{dim.score}/10</span>
                                        </div>
                                        {dim.evidence && (
                                            <p className="text-sm text-gray-600 mb-2">{dim.evidence}</p>
                                        )}
                                        {dim.reason && (
                                            <p className="text-xs text-blue-600 bg-blue-50 rounded-lg px-3 py-1.5">
                                                💡 {dim.reason}
                                            </p>
                                        )}
                                        {dim.improvement_tip && (
                                            <p className="text-xs text-amber-600 bg-amber-50 rounded-lg px-3 py-1.5 mt-1">
                                                🎯 {dim.improvement_tip}
                                            </p>
                                        )}
                                        {dim.better_answer_example && (
                                            <details className="mt-2">
                                                <summary className="text-xs text-emerald-600 cursor-pointer hover:text-emerald-700">
                                                    查看更好的回答示例
                                                </summary>
                                                <p className="text-xs text-gray-600 bg-emerald-50 rounded-lg px-3 py-2 mt-1">
                                                    {dim.better_answer_example}
                                                </p>
                                            </details>
                                        )}
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
