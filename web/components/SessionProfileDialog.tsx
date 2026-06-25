'use client';

import { useState, useEffect } from 'react';
import { Loader2, RefreshCw, Brain, Target, CheckCircle2, Check, AlertCircle } from 'lucide-react';
import { getSessionProfile, type AbilityProfile } from '@/lib/api/profile';
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

export function SessionProfileDialog({ sessionId, open, onOpenChange, defaultTab = 'profile' }: Props) {
    const [activeTab, setActiveTab] = useState<TabType>(defaultTab);
    const [profile, setProfile] = useState<AbilityProfile | null>(null);
    const [loading, setLoading] = useState(true);
    const [generating, setGenerating] = useState(false);

    useEffect(() => {
        if (open && sessionId) {
            loadProfile();
            setActiveTab(defaultTab);
        }
    }, [open, sessionId, defaultTab]);

    async function loadProfile() {
        setLoading(true);
        const response = await getSessionProfile(sessionId);

        if (response.success && response.profile) {
            setProfile(response.profile);
            setGenerating(false);
        } else {
            setProfile(null);
            setGenerating(true); // 画像正在生成中
        }
        setLoading(false);
    }

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                        <Brain className="w-5 h-5 text-orange-600" />
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

                {/* 能力画像 Tab */}
                {activeTab === 'profile' && (
                    <>
                        {/* 加载状态 */}
                        {loading && (
                            <div className="flex flex-col items-center justify-center py-20">
                                <Loader2 className="w-8 h-8 text-orange-600 animate-spin mb-4" />
                                <p className="text-sm text-gray-500">加载中...</p>
                            </div>
                        )}

                        {/* 生成中状态 */}
                        {!loading && generating && (
                            <div className="flex flex-col items-center justify-center py-20 px-6">
                                <div className="w-16 h-16 bg-orange-50 rounded-full flex items-center justify-center mb-4">
                                    <Loader2 className="w-8 h-8 text-orange-600 animate-spin" />
                                </div>
                                <h3 className="text-lg font-semibold text-gray-900 mb-2">画像生成中</h3>
                                <p className="text-sm text-gray-500 text-center mb-6 max-w-sm">
                                    AI 正在分析您的面试表现，请稍等片刻...
                                </p>
                                <Button
                                    onClick={loadProfile}
                                    variant="outline"
                                    className="flex items-center gap-2"
                                >
                                    <RefreshCw className="w-4 h-4" />
                                    刷新
                                </Button>
                            </div>
                        )}

                        {/* 有数据 - 显示画像 */}
                        {!loading && !generating && profile && (
                            <div className="space-y-6">
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
                                                                <span className="text-orange-600 mt-0.5">✓</span>
                                                                <span>{strength}</span>
                                                            </li>
                                                        ))}
                                                    </ul>
                                                </div>
                                            )}
                                            {profile.key_weaknesses && profile.key_weaknesses.length > 0 && (
                                                <div className="bg-orange-50 rounded-xl p-6">
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
                                            {[
                                                { key: 'professional_competence', label: '专业能力' },
                                                { key: 'execution_results', label: '执行与结果导向' },
                                                { key: 'logic_problem_solving', label: '逻辑与问题解决' },
                                                { key: 'communication', label: '沟通表达力' },
                                                { key: 'growth_potential', label: '成长潜力' },
                                                { key: 'collaboration', label: '协作能力' },
                                            ].map(({ key, label }) => {
                                                const dim = profile[key as keyof typeof profile] as any;
                                                if (!dim || typeof dim !== 'object') return null;
                                                return (
                                                    <div key={key} className="border border-gray-100 rounded-lg p-3">
                                                        <div className="flex items-center justify-between mb-1">
                                                            <span className="text-sm font-medium text-gray-900">{label}</span>
                                                            <span className="text-sm font-bold text-orange-600">{dim.score}/10</span>
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
                )}

                {/* 短板地图 Tab */}
                {activeTab === 'weakness' && (
                    <WeaknessMap sessionId={sessionId} autoLoad={true} />
                )}
            </DialogContent>
        </Dialog>
    );
}
