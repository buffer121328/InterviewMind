'use client';

import { useCallback, useEffect, useState } from 'react';
import { RefreshCw, Star } from 'lucide-react';
import { toast } from 'sonner';

import { cn } from '@/lib/utils';
import { satisfactionApi, type SatisfactionAgentType, type SatisfactionFeedbackItem, type SatisfactionStats } from '@/lib/api/satisfaction';
import { formatSatisfactionStats } from '@/lib/satisfaction/satisfactionStats';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ProductionHistoryEvaluationPanel } from './ProductionHistoryEvaluationPanel';

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
export function SatisfactionStatsPanel() {
    const [stats, setStats] = useState<SatisfactionStats | null>(null);
    const [items, setItems] = useState<SatisfactionFeedbackItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [agentType, setAgentType] = useState<SatisfactionAgentType | ''>('');
    const [reviewStatus, setReviewStatus] = useState<SatisfactionFeedbackItem['review_status'] | ''>('');
    const [createdFrom, setCreatedFrom] = useState(''), [createdTo, setCreatedTo] = useState('');
    const [reviewNotes, setReviewNotes] = useState<Record<string, string>>({});

    const refresh = useCallback(async () => {
        setLoading(true); setError(null);
        const filters = {
            agent_type: agentType || undefined, review_status: reviewStatus || undefined,
            created_from: createdFrom ? new Date(`${createdFrom}T00:00:00`).toISOString() : undefined,
            created_to: createdTo ? new Date(`${createdTo}T23:59:59`).toISOString() : undefined,
        };
        try {
            const [nextStats, nextFeedback] = await Promise.all([satisfactionApi.stats(filters), satisfactionApi.feedback(filters)]);
            setStats(nextStats); setItems(nextFeedback.items);
        } catch (reason) {
            setError(reason instanceof Error ? reason.message : '用户反馈加载失败');
        } finally { setLoading(false); }
    }, [agentType, createdFrom, createdTo, reviewStatus]);

    useEffect(() => { const timer = window.setTimeout(() => void refresh(), 0); return () => window.clearTimeout(timer); }, [refresh]);

    async function resolve(item: SatisfactionFeedbackItem) {
        const note = (reviewNotes[item.id] || '').trim();
        if (!note) return toast.warning('请填写复核结论');
        try { await satisfactionApi.resolve(item.id, note); toast.success('反馈已完成复核'); await refresh(); }
        catch (reason) { toast.error(reason instanceof Error ? reason.message : '复核失败'); }
    }

    if (loading) {
        return <section className="rounded-2xl border bg-white p-4 shadow-sm"><h3 className="font-semibold">用户反馈</h3><div className="mt-3"><Empty text="正在加载用户反馈..." /></div></section>;
    }

    if (error) return <section className="rounded-2xl border border-rose-200 bg-white p-4 shadow-sm"><h3 className="font-semibold">用户反馈</h3><p className="mt-2 text-sm text-rose-700">{error}</p><Button className="mt-3" size="sm" variant="outline" onClick={() => void refresh()}><RefreshCw className="mr-2 h-4 w-4" />重试反馈面板</Button><p className="mt-2 text-xs text-slate-500">此错误不会阻断评测运行、数据集或人工标注页面。</p></section>;

    const view = formatSatisfactionStats(stats);
    const filterBar = <section className="rounded-2xl border bg-white p-4 shadow-sm"><div className="flex flex-wrap items-end gap-3"><label className="space-y-1 text-xs">Agent<select className="block h-9 rounded-md border px-3 text-sm" value={agentType} onChange={event => setAgentType(event.target.value as SatisfactionAgentType | '')}><option value="">全部</option><option value="interview">模拟面试</option><option value="resume_optimize">简历优化</option></select></label><label className="space-y-1 text-xs">治理状态<select className="block h-9 rounded-md border px-3 text-sm" value={reviewStatus} onChange={event => setReviewStatus(event.target.value as SatisfactionFeedbackItem['review_status'] | '')}><option value="">全部</option><option value="pending">待复核</option><option value="resolved">已复核</option><option value="not_required">无需复核</option><option value="promoted">已加入评测</option></select></label><label className="space-y-1 text-xs">开始日期<Input type="date" value={createdFrom} onChange={event => setCreatedFrom(event.target.value)} /></label><label className="space-y-1 text-xs">结束日期<Input type="date" value={createdTo} onChange={event => setCreatedTo(event.target.value)} /></label><Button size="sm" variant="outline" onClick={() => void refresh()}><RefreshCw className="mr-2 h-4 w-4" />刷新</Button></div></section>;
    if (!view) return <div className="space-y-4">{filterBar}<Empty text="当前筛选范围暂无用户反馈" /></div>;

    const maxSatisfied = Math.max(...view.satisfiedTop.map(row => row.count), 0);
    const maxDissatisfied = Math.max(...view.dissatisfiedTop.map(row => row.count), 0);

    return <div className="space-y-4">{filterBar}<div className="grid gap-4 xl:grid-cols-[minmax(320px,0.9fr)_minmax(0,1.1fr)]">
        <section className="rounded-2xl border bg-white p-4 shadow-sm">
            <div className="flex items-center justify-between"><div><h3 className="font-semibold">用户反馈汇总</h3><p className="mt-1 text-xs text-slate-500">仅统计当前用户拥有的真实业务记录，可按 Agent 和时间筛选。</p></div><Star className="h-4 w-4 text-amber-400" /></div>
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
    </div><section className="rounded-2xl border bg-white p-4 shadow-sm"><h3 className="font-semibold">反馈明细与治理</h3><p className="mt-1 text-xs text-slate-500">低分或包含不满意方面的反馈自动进入待复核；评论已在后端脱敏。</p><div className="mt-3 space-y-3">{items.map(item => <article key={item.id} className="rounded-xl border p-3 text-sm"><div className="flex flex-wrap items-center justify-between gap-2"><span className="font-medium">{item.agent_type === 'interview' ? '模拟面试' : '简历优化'} · {item.rating == null ? '未评分' : `${item.rating} 星`}</span><span className={cn('rounded-full px-2 py-0.5 text-xs', item.review_status === 'pending' ? 'bg-amber-100 text-amber-800' : 'bg-slate-100 text-slate-600')}>{item.review_status === 'pending' ? '待复核' : item.review_status === 'resolved' ? '已复核' : item.review_status === 'promoted' ? '已加入评测' : '无需复核'}</span></div><p className="mt-1 text-xs text-slate-500">来源：{item.ref_key} · {new Date(item.created_at).toLocaleString()} · {item.source_verified ? '来源已验证' : '历史未验证记录'}</p>{item.comment && <p className="mt-2 whitespace-pre-wrap rounded bg-slate-50 p-2">{item.comment}</p>}{item.dissatisfied_aspects.length > 0 && <p className="mt-2 text-xs text-rose-700">不满意：{item.dissatisfied_aspects.join('、')}</p>}{item.review_note && <p className="mt-2 text-xs text-teal-700">复核结论：{item.review_note}</p>}{item.review_status === 'pending' && <div className="mt-3 flex gap-2"><Input value={reviewNotes[item.id] || ''} onChange={event => setReviewNotes(current => ({ ...current, [item.id]: event.target.value }))} placeholder="填写复核结论" /><Button size="sm" onClick={() => void resolve(item)}>完成复核</Button></div>}{item.review_status === 'resolved' && <div className="mt-3"><ProductionHistoryEvaluationPanel capability={item.agent_type === 'interview' ? 'interview_planner' : 'resume_optimizer'} sourceId={item.ref_key} feedbackId={item.id} onCreated={() => void refresh()} /></div>}{item.candidate_dataset_id && <p className="mt-2 text-xs text-emerald-700">已关联数据集：{item.candidate_dataset_id}</p>}</article>)}{items.length === 0 && <Empty text="暂无反馈明细" />}</div></section></div>;
}
