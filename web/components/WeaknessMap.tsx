'use client';

import { useState, useEffect } from 'react';
import {
    Loader2,
    RefreshCw,
    AlertCircle,
    Target,
    ChevronDown,
    ChevronUp,
    Lightbulb,
    BookOpen,
    ArrowRight,
    Zap
} from 'lucide-react';
import {
    getSessionWeaknessReport,
    type WeaknessReport
} from '@/lib/api/weakness';
import { createInterviewReportRun, pollAgentRun } from '@/lib/api/agentRuns';
import { getRequestApiConfig } from '@/store/interviewFacade';
import { Button } from './ui/button';
import { cn } from '@/lib/utils';

interface WeaknessMapProps {
    sessionId: string;
    /** 是否自动加载报告 */
    autoLoad?: boolean;
}

// 严重程度颜色映射
const SEVERITY_STYLES: Record<string, { bg: string; text: string; border: string; label: string }> = {
    high: { bg: 'bg-red-50', text: 'text-red-700', border: 'border-red-200', label: '高' },
    medium: { bg: 'bg-amber-50', text: 'text-amber-700', border: 'border-amber-200', label: '中' },
    low: { bg: 'bg-blue-50', text: 'text-blue-700', border: 'border-blue-200', label: '低' },
};

// 优先级颜色
const PRIORITY_STYLES: Record<number, string> = {
    1: 'bg-red-100 text-red-700',
    2: 'bg-orange-100 text-orange-700',
    3: 'bg-amber-100 text-amber-700',
    4: 'bg-blue-100 text-blue-700',
    5: 'bg-gray-100 text-gray-700',
};

export function WeaknessMap({ sessionId, autoLoad = true }: WeaknessMapProps) {
    const [report, setReport] = useState<WeaknessReport | null>(null);
    const [loading, setLoading] = useState(true);
    const [generating, setGenerating] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [expandedFailures, setExpandedFailures] = useState<Set<number>>(new Set());

    useEffect(() => {
        if (!autoLoad || !sessionId) return;

        let active = true;
        void getSessionWeaknessReport(sessionId).then((response) => {
            if (!active) return;

            if (response.success && response.report) {
                setReport(response.report);
            } else {
                setReport(null);
            }
            setLoading(false);
        });

        return () => {
            active = false;
        };
    }, [sessionId, autoLoad]);

    async function handleGenerate() {
        setGenerating(true);
        setError(null);

        const apiConfig = getRequestApiConfig();
        if (!apiConfig) {
            setError('请先在设置中配置 API Key');
            setGenerating(false);
            return;
        }

        try {
            const created = await createInterviewReportRun({ session_id: sessionId, api_config: apiConfig });
            if ('run_id' in created) {
                const completed = await pollAgentRun(created.run_id);
                if (completed.status !== 'succeeded') {
                    setError(completed.error_message || '报告任务执行失败');
                    return;
                }
            }
            const response = await getSessionWeaknessReport(sessionId);
            if (response.success && response.report) {
                setReport(response.report);
            } else {
                setError(response.message || '生成失败，请稍后重试');
            }
        } catch (cause) {
            setError(cause instanceof Error ? cause.message : '生成失败，请稍后重试');
        } finally {
            setGenerating(false);
        }
    }

    function toggleFailure(index: number) {
        setExpandedFailures(prev => {
            const next = new Set(prev);
            if (next.has(index)) {
                next.delete(index);
            } else {
                next.add(index);
            }
            return next;
        });
    }

    // 加载状态
    if (loading) {
        return (
            <div className="flex flex-col items-center justify-center py-16">
                <Loader2 className="w-8 h-8 text-orange-600 animate-spin mb-4" />
                <p className="text-sm text-gray-500">加载短板地图...</p>
            </div>
        );
    }

    // 空状态
    if (!report) {
        return (
            <div className="flex flex-col items-center justify-center py-16 px-6">
                <div className="w-16 h-16 bg-orange-50 rounded-full flex items-center justify-center mb-4">
                    <Target className="w-8 h-8 text-orange-500" />
                </div>
                <h3 className="text-lg font-semibold text-gray-900 mb-2">暂无短板地图</h3>
                <p className="text-sm text-gray-500 text-center mb-6 max-w-sm">
                    生成短板地图，了解面试中的薄弱环节和改进方向
                </p>
                <Button
                    onClick={handleGenerate}
                    disabled={generating}
                    className="bg-orange-600 hover:bg-orange-700 text-white px-6 py-2 rounded-lg flex items-center gap-2"
                >
                    {generating ? (
                        <>
                            <Loader2 className="w-4 h-4 animate-spin" />
                            生成中...
                        </>
                    ) : (
                        <>
                            <Zap className="w-4 h-4" />
                            生成短板地图
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

    const { report_data } = report;
    const hasData = report_data.weakness_categories.length > 0 ||
        report_data.question_failures.length > 0 ||
        report_data.improvement_actions.length > 0;

    return (
        <div className="space-y-6">
            {/* 标题和操作栏 */}
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                    <div className="w-10 h-10 bg-orange-100 rounded-xl flex items-center justify-center">
                        <Target className="w-5 h-5 text-orange-600" />
                    </div>
                    <div>
                        <h3 className="text-lg font-bold text-gray-900">面试短板地图</h3>
                        <p className="text-xs text-gray-500">
                            生成时间: {new Date(report.created_at).toLocaleString('zh-CN')}
                        </p>
                    </div>
                </div>
                <Button
                    onClick={handleGenerate}
                    disabled={generating}
                    variant="outline"
                    size="sm"
                    className="flex items-center gap-2"
                >
                    {generating ? (
                        <>
                            <Loader2 className="w-4 h-4 animate-spin" />
                            重新生成中...
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

            {!hasData && (
                <div className="text-center py-8 text-gray-500 text-sm">
                    暂无分析数据，请重新生成
                </div>
            )}

            {/* 短板分类 */}
            {report_data.weakness_categories.length > 0 && (
                <div className="space-y-3">
                    <h4 className="text-base font-semibold text-gray-900 flex items-center gap-2">
                        <span className="w-1 h-5 bg-orange-500 rounded-full inline-block"></span>
                        短板分类
                    </h4>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        {report_data.weakness_categories.map((cat, index) => {
                            const style = SEVERITY_STYLES[cat.severity] || SEVERITY_STYLES.medium;
                            return (
                                <div
                                    key={index}
                                    className={cn(
                                        'rounded-xl border p-4 transition-all hover:shadow-sm',
                                        style.bg, style.border
                                    )}
                                >
                                    <div className="flex items-center justify-between mb-2">
                                        <span className="font-medium text-gray-900">{cat.category}</span>
                                        <span className={cn(
                                            'text-xs px-2 py-0.5 rounded-full font-medium',
                                            style.bg, style.text
                                        )}>
                                            {style.label}
                                        </span>
                                    </div>
                                    <p className="text-sm text-gray-600 leading-relaxed">
                                        {cat.description}
                                    </p>
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}

            {/* 问题失败分析 */}
            {report_data.question_failures.length > 0 && (
                <div className="space-y-3">
                    <h4 className="text-base font-semibold text-gray-900 flex items-center gap-2">
                        <span className="w-1 h-5 bg-red-500 rounded-full inline-block"></span>
                        典型问题分析
                    </h4>
                    <div className="space-y-3">
                        {report_data.question_failures.map((failure, index) => (
                            <div
                                key={index}
                                className="bg-white rounded-xl border border-gray-200 overflow-hidden hover:shadow-sm transition-all"
                            >
                                <button
                                    onClick={() => toggleFailure(index)}
                                    className="w-full px-4 py-3 flex items-center justify-between text-left hover:bg-gray-50 transition-colors"
                                >
                                    <div className="flex-1 min-w-0">
                                        <p className="text-sm font-medium text-gray-900 truncate">
                                            {failure.question}
                                        </p>
                                        <p className="text-xs text-gray-500 mt-0.5 truncate">
                                            {failure.issue}
                                        </p>
                                    </div>
                                    {expandedFailures.has(index) ? (
                                        <ChevronUp className="w-4 h-4 text-gray-400 flex-shrink-0 ml-2" />
                                    ) : (
                                        <ChevronDown className="w-4 h-4 text-gray-400 flex-shrink-0 ml-2" />
                                    )}
                                </button>
                                {expandedFailures.has(index) && (
                                    <div className="px-4 pb-4 space-y-3 border-t border-gray-100 pt-3">
                                        <div>
                                            <p className="text-xs font-medium text-gray-500 mb-1">你的回答</p>
                                            <p className="text-sm text-gray-700 bg-gray-50 rounded-lg p-3">
                                                {failure.user_answer}
                                            </p>
                                        </div>
                                        <div>
                                            <p className="text-xs font-medium text-red-600 mb-1">核心问题</p>
                                            <p className="text-sm text-red-700">{failure.issue}</p>
                                        </div>
                                        <div>
                                            <p className="text-xs font-medium text-emerald-600 mb-1">改进方向</p>
                                            <p className="text-sm text-emerald-700 bg-emerald-50 rounded-lg p-3">
                                                {failure.better_example}
                                            </p>
                                        </div>
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* 改进行动项 */}
            {report_data.improvement_actions.length > 0 && (
                <div className="space-y-3">
                    <h4 className="text-base font-semibold text-gray-900 flex items-center gap-2">
                        <span className="w-1 h-5 bg-orange-500 rounded-full inline-block"></span>
                        改进行动
                    </h4>
                    <div className="space-y-2">
                        {report_data.improvement_actions
                            .sort((a, b) => a.priority - b.priority)
                            .map((action, index) => (
                                <div
                                    key={index}
                                    className="flex items-start gap-3 p-3 bg-white rounded-xl border border-gray-200 hover:shadow-sm transition-all"
                                >
                                    <span className={cn(
                                        'flex-shrink-0 w-7 h-7 rounded-lg flex items-center justify-center text-xs font-bold',
                                        PRIORITY_STYLES[action.priority] || PRIORITY_STYLES[3]
                                    )}>
                                        {action.priority}
                                    </span>
                                    <div className="flex-1 min-w-0">
                                        <p className="text-sm text-gray-900">{action.action}</p>
                                        <p className="text-xs text-gray-500 mt-1">
                                            预估投入: {action.estimated_effort}
                                        </p>
                                    </div>
                                </div>
                            ))}
                    </div>
                </div>
            )}

            {/* 推荐练习题 */}
            {report_data.recommended_questions.length > 0 && (
                <div className="space-y-3">
                    <h4 className="text-base font-semibold text-gray-900 flex items-center gap-2">
                        <BookOpen className="w-5 h-5 text-purple-500" />
                        推荐练习题
                    </h4>
                    <div className="bg-purple-50/60 rounded-xl border border-purple-100 p-4">
                        <ul className="space-y-3">
                            {report_data.recommended_questions.map((q, index) => (
                                <li key={index} className="flex items-start gap-3">
                                    <span className="flex-shrink-0 w-6 h-6 rounded-full bg-purple-100 text-purple-600 flex items-center justify-center text-xs font-bold mt-0.5">
                                        {index + 1}
                                    </span>
                                    <span className="text-sm text-gray-700 leading-relaxed">{q}</span>
                                </li>
                            ))}
                        </ul>
                    </div>
                </div>
            )}

            {/* 优先级排序提示 */}
            {report_data.priority_order.length > 0 && (
                <div className="bg-gradient-to-r from-orange-50 to-amber-50 rounded-xl border border-orange-100 p-4">
                    <div className="flex items-start gap-3">
                        <Lightbulb className="w-5 h-5 text-orange-500 mt-0.5 flex-shrink-0" />
                        <div>
                            <p className="text-sm font-medium text-orange-800 mb-1">建议练习顺序</p>
                            <div className="flex flex-wrap items-center gap-2">
                                {report_data.priority_order.map((cat, index) => (
                                    <span key={index} className="flex items-center gap-1">
                                        <span className="text-sm text-orange-700 font-medium">{cat}</span>
                                        {index < report_data.priority_order.length - 1 && (
                                            <ArrowRight className="w-3 h-3 text-orange-400" />
                                        )}
                                    </span>
                                ))}
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
