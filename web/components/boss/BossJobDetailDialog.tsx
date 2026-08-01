'use client';

import { Building2, ExternalLink, FileText, Loader2, MapPin } from 'lucide-react';

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
import { ASSET_STATUS_LABELS, asRecord, readStringList } from '@/lib/bossCenter';
import { BossGreetingEditorList } from '@/components/boss/BossGreetingEditorList';

interface BossJobDetailDialogProps {
    open: boolean;
    onClose: () => void;
    selectedJob: JobDetail | null;
    loading: boolean;
    error: string | null;
    actionKey: string | null;
    onOpenExistingBossTab: (jobId: number) => void;
    onSaveGreeting: (jobId: number, greetingIndex: number, messageText: string) => void;
    onExportGreeting: (jobId: number, greetingIndex: number, messageText: string) => void;
    onEditGreeting: (greetingIndex: number, value: string) => void;
}

/** Shows and edits one imported job's persisted delivery assets; it never previews, fills or sends BOSS messages. */
export function BossJobDetailDialog({
    open,
    onClose,
    selectedJob,
    loading,
    error,
    actionKey,
    onOpenExistingBossTab,
    onSaveGreeting,
    onExportGreeting,
    onEditGreeting,
}: BossJobDetailDialogProps) {
    const detailAsset = selectedJob?.asset_payload || null;
    const detailGreetings = detailAsset?.greetings || [];
    const detailJdAnalysis = asRecord(detailAsset?.jd_analysis);
    const detailMatched = readStringList(detailJdAnalysis, "matched_keywords");
    const detailMissing = readStringList(detailJdAnalysis, "missing_keywords");
    const detailStrengths = readStringList(detailJdAnalysis, "strengths");
    const detailRisks = readStringList(detailJdAnalysis, "risks");

    return (
        <Dialog open={open} onOpenChange={openChange => {
            if (!openChange) onClose();
        }}>
            <DialogContent className="max-h-[92vh] max-w-4xl overflow-y-auto">
                <DialogHeader>
                    <DialogTitle>岗位资产详情</DialogTitle>
                    <DialogDescription>这里只展示和编辑投递资产；不会预览、填写或发送 BOSS 消息。</DialogDescription>
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
                                        {selectedJob.company_name || "公司未披露"}
                                        {selectedJob.company_size_text && <span>· {selectedJob.company_size_text}</span>}
                                    </div>
                                </div>
                                <Badge className="bg-teal-50 text-teal-700 hover:bg-teal-50">
                                    匹配度 {selectedJob.match_score != null ? `${selectedJob.match_score}%` : "待分析"}
                                </Badge>
                            </div>
                            <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                                <Badge variant="outline">{selectedJob.salary_text || "薪资未披露"}</Badge>
                                {selectedJob.city && <span className="inline-flex items-center gap-1"><MapPin className="h-3 w-3" />{selectedJob.city}</span>}
                                {selectedJob.asset_status && <Badge variant="outline">{ASSET_STATUS_LABELS[selectedJob.asset_status] || selectedJob.asset_status}</Badge>}
                                {detailAsset?.custom_resume_id && <Badge variant="outline">定制简历 #{detailAsset.custom_resume_id}</Badge>}
                            </div>
                            <div className="mt-4 flex flex-wrap gap-2">
                                <Button variant="outline" disabled={actionKey !== null} onClick={() => void onOpenExistingBossTab(selectedJob.id)}>
                                    {actionKey === `open:${selectedJob.id}` ? <Loader2 className="animate-spin" /> : <ExternalLink />}
                                    在已有 BOSS 标签页打开
                                </Button>
                            </div>
                            {selectedJob.source_url && <p className="mt-3 break-all font-mono text-[10px] text-slate-400">{selectedJob.source_url}</p>}
                        </section>

                        <section className="rounded-xl border border-slate-200 p-4">
                            <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-900"><FileText className="h-4 w-4" />职位介绍</h3>
                            <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-700">{selectedJob.job_description || "当前岗位没有可展示的职位介绍。"}</p>
                        </section>

                        <section className="rounded-xl border border-slate-200 p-4">
                            <h3 className="text-sm font-semibold text-slate-900">JD 匹配分析</h3>
                            {!detailJdAnalysis ? (
                                <p className="mt-3 text-sm text-slate-500">详细 JD 分析尚未生成；岗位库仍保留初筛匹配度。</p>
                            ) : (
                                <div className="mt-3 grid gap-4 md:grid-cols-2">
                                    <div>
                                        <div className="text-xs font-semibold text-emerald-700">匹配关键词</div>
                                        <div className="mt-2 flex flex-wrap gap-1">{detailMatched.map(item => <Badge key={item} variant="outline">{item}</Badge>)}</div>
                                    </div>
                                    <div>
                                        <div className="text-xs font-semibold text-amber-700">缺失关键词</div>
                                        <div className="mt-2 flex flex-wrap gap-1">{detailMissing.map(item => <Badge key={item} variant="outline">{item}</Badge>)}</div>
                                    </div>
                                    {detailStrengths.length > 0 && <div><div className="text-xs font-semibold text-slate-700">优势</div><ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-slate-600">{detailStrengths.map(item => <li key={item}>{item}</li>)}</ul></div>}
                                    {detailRisks.length > 0 && <div><div className="text-xs font-semibold text-red-700">风险</div><ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-slate-600">{detailRisks.map(item => <li key={item}>{item}</li>)}</ul></div>}
                                </div>
                            )}
                        </section>

                        <section>
                            <h3 className="mb-3 text-sm font-semibold text-slate-900">打招呼方案（可编辑）</h3>
                            <BossGreetingEditorList
                                jobId={selectedJob.id}
                                greetings={detailGreetings}
                                actionKey={actionKey}
                                onChange={onEditGreeting}
                                onSave={onSaveGreeting}
                                onExport={onExportGreeting}
                            />
                        </section>
                    </div>
                )}
            </DialogContent>
        </Dialog>
    );
}
