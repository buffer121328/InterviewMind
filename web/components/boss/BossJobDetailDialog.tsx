'use client';

import { Building2, ExternalLink, FileText, Loader2, MapPin, Sparkles } from 'lucide-react';

import { JobDescriptionContent } from '@/components/boss/JobDescriptionContent';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog';
import type { JobDetail } from '@/lib/api/jobs';
import { asRecord, readStringList } from '@/lib/bossCenter';

interface BossJobDetailDialogProps {
    open: boolean;
    onClose: () => void;
    selectedJob: JobDetail | null;
    loading: boolean;
    error: string | null;
    analysisError: string | null;
    actionKey: string | null;
    onOpenExistingBossTab: (jobId: number) => void;
    onAnalyzeJd: () => void;
    onUseInInterview: () => void;
    onImportToResume: () => void;
}

function readNumber(record: Record<string, unknown> | null, key: string): number | null {
    const value = record?.[key];
    return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/** Shows one imported job's persisted details and lets its owner explicitly generate a JD analysis. */
export function BossJobDetailDialog({
    open,
    onClose,
    selectedJob,
    loading,
    error,
    analysisError,
    actionKey,
    onOpenExistingBossTab,
    onAnalyzeJd,
    onUseInInterview,
    onImportToResume,
}: BossJobDetailDialogProps) {
    const detailAsset = selectedJob?.asset_payload || null;
    const detailAssetRecord = asRecord(detailAsset);
    const detailJdAnalysis = asRecord(detailAsset?.jd_analysis);
    const detailMatched = readStringList(detailJdAnalysis, 'matched_keywords');
    const detailMissing = readStringList(detailJdAnalysis, 'missing_keywords');
    const detailStrengths = readStringList(detailJdAnalysis, 'strengths');
    const detailRisks = readStringList(detailJdAnalysis, 'risks');
    const detailPriorityActions = readStringList(detailJdAnalysis, 'priority_actions');
    const detailedScore = readNumber(detailJdAnalysis, 'overall_match_score');
    const preliminaryScore = readNumber(detailAssetRecord, 'preliminary_match_score');
    const analysisActionKey = selectedJob ? `jd-analysis:${selectedJob.id}` : '';
    const analysisRunning = actionKey === analysisActionKey;

    return (
        <Dialog open={open} onOpenChange={openChange => {
            if (!openChange) onClose();
        }}>
            <DialogContent className="max-h-[92vh] max-w-4xl overflow-y-auto">
                <DialogHeader>
                    <DialogTitle>岗位资产详情</DialogTitle>
                    <DialogDescription>这里展示岗位详情与 JD 分析；JD 分析需由你主动发起，不会生成简历、发送消息或投递岗位。</DialogDescription>
                </DialogHeader>
                {loading && <div className="flex items-center justify-center py-20 text-sm text-slate-500"><Loader2 className="mr-2 animate-spin" />加载岗位资产...</div>}
                {error && <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">{error}</div>}
                {selectedJob && (
                    <div className="space-y-5">
                        <section className="rounded-xl border border-slate-200 p-4">
                            <div className="flex flex-wrap items-start justify-between gap-3">
                                <div>
                                    <h3 className="text-lg font-semibold text-slate-950">{selectedJob.job_title}</h3>
                                    <div className="mt-1 flex items-center gap-2 text-sm text-slate-600">
                                        <Building2 className="h-4 w-4" />
                                        {selectedJob.company_name || '公司未披露'}
                                        {selectedJob.company_size_text && <span>· {selectedJob.company_size_text}</span>}
                                    </div>
                                </div>
                                <Badge className="bg-teal-50 text-teal-700 hover:bg-teal-50">
                                    {detailedScore != null ? `JD 分析匹配度 ${detailedScore}%` : `初筛匹配度 ${selectedJob.match_score != null ? `${selectedJob.match_score}%` : '待计算'}`}
                                </Badge>
                            </div>
                            <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                                <Badge variant="outline">{selectedJob.salary_text || '薪资未披露'}</Badge>
                                {selectedJob.city && <span className="inline-flex items-center gap-1"><MapPin className="h-3 w-3" />{selectedJob.city}</span>}
                                {detailedScore != null && preliminaryScore != null && <Badge variant="outline">初筛匹配度 {preliminaryScore}%</Badge>}
                            </div>
                            <div className="mt-4 flex flex-wrap gap-2">
                                <Button onClick={onUseInInterview}>用于模拟面试</Button>
                                <Button variant="secondary" onClick={onImportToResume}>导入简历工作台</Button>
                                <Button variant="outline" disabled={actionKey !== null} onClick={() => void onOpenExistingBossTab(selectedJob.id)}>
                                    {actionKey === `open:${selectedJob.id}` ? <Loader2 className="animate-spin" /> : <ExternalLink />}
                                    在已有 BOSS 标签页打开
                                </Button>
                            </div>
                            {selectedJob.source_url && <p className="mt-3 break-all font-mono text-[10px] text-slate-400">{selectedJob.source_url}</p>}
                        </section>

                        <section className="rounded-xl border border-slate-200 p-4">
                            <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-900"><FileText className="h-4 w-4" />职位介绍</h3>
                            {selectedJob.job_description ? (
                                <JobDescriptionContent description={selectedJob.job_description} className="mt-3 text-sm leading-6 text-slate-700" />
                            ) : (
                                <p className="mt-3 text-sm text-slate-500">当前岗位没有可展示的职位介绍。</p>
                            )}
                        </section>

                        <section className="rounded-xl border border-slate-200 p-4">
                            <div className="flex flex-wrap items-center justify-between gap-3">
                                <div>
                                    <h3 className="text-sm font-semibold text-slate-900">JD 匹配分析</h3>
                                    {!detailJdAnalysis && <p className="mt-1 text-xs text-slate-500">当前仅保留采集阶段的初筛匹配度。开始分析会使用当前简历与本岗位完整 JD。</p>}
                                </div>
                                <Button size="sm" disabled={actionKey !== null} onClick={onAnalyzeJd}>
                                    {analysisRunning ? <Loader2 className="animate-spin" /> : <Sparkles />}
                                    {analysisRunning ? '分析中…' : detailJdAnalysis ? '重新进行 JD 匹配分析' : '开始 JD 匹配分析'}
                                </Button>
                            </div>
                            {analysisError && <div className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">{analysisError}</div>}
                            {!detailJdAnalysis ? (
                                <p className="mt-3 text-sm text-slate-500">详细 JD 分析尚未生成；不会自动生成或修改简历，也不会触发投递。</p>
                            ) : (
                                <div className="mt-4 space-y-4">
                                    <div className="rounded-lg bg-teal-50 p-3 text-sm text-teal-900">JD 分析匹配度 <span className="text-lg font-semibold">{detailedScore != null ? `${detailedScore}%` : '待确认'}</span></div>
                                    <div className="grid gap-4 md:grid-cols-2">
                                        <div>
                                            <div className="text-xs font-semibold text-emerald-700">匹配关键词</div>
                                            <div className="mt-2 flex flex-wrap gap-1">{detailMatched.length ? detailMatched.map(item => <Badge key={item} variant="outline">{item}</Badge>) : <span className="text-xs text-slate-500">暂无</span>}</div>
                                        </div>
                                        <div>
                                            <div className="text-xs font-semibold text-amber-700">缺失关键词</div>
                                            <div className="mt-2 flex flex-wrap gap-1">{detailMissing.length ? detailMissing.map(item => <Badge key={item} variant="outline">{item}</Badge>) : <span className="text-xs text-slate-500">暂无</span>}</div>
                                        </div>
                                        {detailStrengths.length > 0 && <div><div className="text-xs font-semibold text-slate-700">优势</div><ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-slate-600">{detailStrengths.map(item => <li key={item}>{item}</li>)}</ul></div>}
                                        {detailRisks.length > 0 && <div><div className="text-xs font-semibold text-red-700">风险</div><ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-slate-600">{detailRisks.map(item => <li key={item}>{item}</li>)}</ul></div>}
                                    </div>
                                    {detailPriorityActions.length > 0 && <div><div className="text-xs font-semibold text-indigo-700">优先改进建议</div><ol className="mt-2 list-decimal space-y-1 pl-5 text-xs text-slate-600">{detailPriorityActions.map(item => <li key={item}>{item}</li>)}</ol></div>}
                                </div>
                            )}
                        </section>
                    </div>
                )}
            </DialogContent>
        </Dialog>
    );
}
