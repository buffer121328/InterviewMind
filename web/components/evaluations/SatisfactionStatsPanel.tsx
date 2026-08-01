'use client';

import { Star } from 'lucide-react';

import { cn } from '@/lib/utils';
import type { SatisfactionStats } from '@/lib/api/satisfaction';
import { formatSatisfactionStats } from '@/lib/satisfaction/satisfactionStats';

interface SatisfactionStatsPanelProps {
    stats: SatisfactionStats | null;
    loading: boolean;
}

/** 空态占位（参考 EvaluationGovernancePanels 的 Empty 风格） */
function Empty({ text }: { text: string }) {
    return <div className="rounded-xl border border-dashed p-6 text-center text-sm text-slate-500">{text}</div>;
}

/** 汇总小卡 */
function Metric({ label, value }: { label: string; value: string | number }) {
    return <div className="rounded-xl border bg-slate-50 p-3"><div className="text-[11px] text-slate-500">{label}</div><div className="mt-1 font-semibold text-slate-900">{value}</div></div>;
}

/**
 * 评测中心"用户反馈"统计面板：汇总、星级分布与满意/不满意方面 Top。
 * 纯展示组件，数据来自父组件刷新的满意度统计。
 */
export function SatisfactionStatsPanel({ stats, loading }: SatisfactionStatsPanelProps) {
    if (loading) {
        return <section className="rounded-2xl border bg-white p-4 shadow-sm"><h3 className="font-semibold">用户反馈</h3><div className="mt-3"><Empty text="正在加载用户反馈..." /></div></section>;
    }

    if (!stats || stats.total_count === 0) {
        return <section className="rounded-2xl border bg-white p-4 shadow-sm"><h3 className="font-semibold">用户反馈</h3><div className="mt-3"><Empty text="暂无用户反馈" /></div></section>;
    }

    const view = formatSatisfactionStats(stats);
    if (!view) return <Empty text="暂无用户反馈" />;

    const maxSatisfied = Math.max(...view.satisfiedTop.map(row => row.count), 0);
    const maxDissatisfied = Math.max(...view.dissatisfiedTop.map(row => row.count), 0);

    return <div className="grid gap-4 xl:grid-cols-[minmax(320px,0.9fr)_minmax(0,1.1fr)]">
        <section className="rounded-2xl border bg-white p-4 shadow-sm">
            <div className="flex items-center justify-between"><div><h3 className="font-semibold">用户反馈汇总</h3><p className="mt-1 text-xs text-slate-500">匿名计入评测统计，不关联个人身份。</p></div><Star className="h-4 w-4 text-amber-400" /></div>
            <div className="mt-3 grid grid-cols-3 gap-2">
                <Metric label="提交量" value={view.totalCount} />
                <Metric label="已评分" value={view.ratingCount} />
                <Metric label="平均星级" value={view.avgRating} />
            </div>
            <div className="mt-5">
                <h4 className="text-sm font-semibold text-slate-700">星级分布</h4>
                <div className="mt-3 space-y-2">
                    {view.distribution.map(row => (
                        <div key={row.star} className="flex items-center gap-2">
                            <span className="w-12 shrink-0 text-xs text-slate-500">{row.star} 星</span>
                            <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-slate-100">
                                <div
                                    className={cn('h-full rounded-full transition-all', row.star >= 4 ? 'bg-amber-400' : row.star === 3 ? 'bg-amber-300' : 'bg-slate-300')}
                                    style={{ width: `${Math.max(2, Math.round(row.ratio * 100))}%` }}
                                />
                            </div>
                            <span className="w-12 shrink-0 text-right text-xs text-slate-500">{row.count}</span>
                        </div>
                    ))}
                </div>
            </div>
        </section>

        <section className="rounded-2xl border bg-white p-4 shadow-sm">
            <h3 className="font-semibold">方面频次 Top</h3>
            <div className="mt-3 grid gap-4 sm:grid-cols-2">
                <div>
                    <h4 className="text-sm font-semibold text-teal-700">满意的方面</h4>
                    <div className="mt-2 space-y-2">
                        {view.satisfiedTop.length === 0 && <p className="text-xs text-slate-400">暂无满意的方面反馈</p>}
                        {view.satisfiedTop.map(row => (
                            <div key={row.aspect} className="flex items-center gap-2">
                                <span className="flex-1 truncate text-sm text-slate-700">{row.aspect}</span>
                                <div className="h-1.5 w-24 overflow-hidden rounded-full bg-slate-100">
                                    <div className="h-full rounded-full bg-teal-400" style={{ width: `${maxSatisfied > 0 ? Math.round((row.count / maxSatisfied) * 100) : 0}%` }} />
                                </div>
                                <span className="w-28 shrink-0 text-right text-xs text-slate-500">{row.aspect} ({row.count})</span>
                            </div>
                        ))}
                    </div>
                </div>
                <div>
                    <h4 className="text-sm font-semibold text-rose-600">不满意的方面</h4>
                    <div className="mt-2 space-y-2">
                        {view.dissatisfiedTop.length === 0 && <p className="text-xs text-slate-400">暂无不满意的方面反馈</p>}
                        {view.dissatisfiedTop.map(row => (
                            <div key={row.aspect} className="flex items-center gap-2">
                                <span className="flex-1 truncate text-sm text-slate-700">{row.aspect}</span>
                                <div className="h-1.5 w-24 overflow-hidden rounded-full bg-slate-100">
                                    <div className="h-full rounded-full bg-rose-400" style={{ width: `${maxDissatisfied > 0 ? Math.round((row.count / maxDissatisfied) * 100) : 0}%` }} />
                                </div>
                                <span className="w-28 shrink-0 text-right text-xs text-slate-500">{row.aspect} ({row.count})</span>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        </section>
    </div>;
}
