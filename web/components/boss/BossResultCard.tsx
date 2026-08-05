'use client';

import { AlertTriangle, ExternalLink, Loader2, MapPin, Trash2 } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { CapturedJobSummary } from '@/lib/api/jobs';
import { BossGreetingEditorList } from '@/components/boss/BossGreetingEditorList';

interface BossResultCardProps {
    job: CapturedJobSummary;
    actionKey: string | null;
    onDeletePending: (job: CapturedJobSummary) => void;
    onOpenExistingBossTab: (jobId: number) => void;
    onEditGreeting: (jobId: number, index: number, value: string) => void;
    onSaveGreeting: (jobId: number, greetingIndex: number, messageText: string) => void;
    onExportGreeting: (jobId: number, greetingIndex: number, messageText: string) => void;
}

/** Renders one current-import result card with its persisted assets and match score. */
export function BossResultCard({
    job,
    actionKey,
    onDeletePending,
    onOpenExistingBossTab,
    onEditGreeting,
    onSaveGreeting,
    onExportGreeting,
}: BossResultCardProps) {
    if (job.job_id == null) {
        return (
            <Card className="border-slate-200 shadow-sm">
                <CardHeader className="pb-3">
                    <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
                        <div className="min-w-0">
                            <CardTitle className="text-base">{job.job_title}</CardTitle>
                            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-600">
                                <span className="font-medium">{job.company_name || "公司未披露"}</span>
                                {job.company_size_text && <span>· {job.company_size_text}</span>}
                            </div>
                            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                                <Badge variant="outline">{job.salary_text || "薪资未披露"}</Badge>
                                {job.city && <span className="inline-flex items-center gap-1"><MapPin className="h-3 w-3" />{job.city}</span>}
                                <Badge variant="outline" className="border-amber-200 bg-amber-50 text-amber-700">待入库</Badge>
                            </div>
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                            <Badge className="bg-teal-50 text-teal-700 hover:bg-teal-50">
                                匹配度 {job.match_score != null ? `${job.match_score}%` : "计算中"}
                            </Badge>
                            <Button
                                variant="outline"
                                size="sm"
                                className="text-red-600 hover:bg-red-50 hover:text-red-700"
                                disabled={actionKey !== null}
                                onClick={() => onDeletePending(job)}
                            >
                                <Trash2 className="h-4 w-4" />
                                删除
                            </Button>
                        </div>
                    </div>
                </CardHeader>
                <CardContent className="space-y-4">
                    {job.job_description && (
                        <div className="rounded-xl border border-slate-200 bg-white p-3">
                            <div className="text-xs font-semibold text-slate-700">当前卡片可见职位介绍</div>
                            <p className="mt-2 whitespace-pre-wrap text-xs leading-5 text-slate-600">{job.job_description}</p>
                        </div>
                    )}
                    <div className="flex items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
                        <AlertTriangle className="h-4 w-4 shrink-0" />尚未入库：确认无误后点击上方「一键入库」写入岗位库；后续可在模拟面试或简历工作台显式使用，或删除这张卡片。
                    </div>
                </CardContent>
            </Card>
        );
    }
    // 早退已保证 job_id 非空；提取为 const 使闭包回调中的类型收窄保持生效
    const jobId = job.job_id;
    return (
        <Card className="border-slate-200 shadow-sm">
            <CardHeader className="pb-3">
                <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
                    <div className="min-w-0">
                        <CardTitle className="text-base">{job.job_title}</CardTitle>
                        <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-600">
                            <span className="font-medium">{job.company_name || "公司未披露"}</span>
                            {job.company_size_text && <span>· {job.company_size_text}</span>}
                        </div>
                        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                            <Badge variant="outline">{job.salary_text || "薪资未披露"}</Badge>
                            {job.city && <span className="inline-flex items-center gap-1"><MapPin className="h-3 w-3" />{job.city}</span>}
                        </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        <Badge className="bg-teal-50 text-teal-700 hover:bg-teal-50">
                            匹配度 {job.match_score != null ? `${job.match_score}%` : "计算中"}
                        </Badge>
                        <Button
                            variant="outline"
                            size="sm"
                            disabled={actionKey !== null}
                            onClick={() => void onOpenExistingBossTab(jobId)}
                        >
                            {actionKey === `open:${jobId}` ? <Loader2 className="animate-spin" /> : <ExternalLink />}
                            已有标签页打开
                        </Button>
                    </div>
                </div>
            </CardHeader>
            <CardContent className="space-y-4">
                {job.job_description && (
                    <div className="rounded-xl border border-slate-200 bg-white p-3">
                        <div className="text-xs font-semibold text-slate-700">当前卡片可见职位介绍</div>
                        <p className="mt-2 whitespace-pre-wrap text-xs leading-5 text-slate-600">{job.job_description}</p>
                    </div>
                )}
                <BossGreetingEditorList
                    jobId={jobId}
                    greetings={job.greetings}
                    actionKey={actionKey}
                    onChange={(index, value) => onEditGreeting(jobId, index, value)}
                    onSave={onSaveGreeting}
                    onExport={onExportGreeting}
                />
                {job.risk_flags.length > 0 && (
                    <div className="flex items-start gap-2 rounded-xl bg-amber-50 p-3 text-xs text-amber-800">
                        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                        <ul className="space-y-1">{job.risk_flags.map(flag => <li key={flag}>{flag}</li>)}</ul>
                    </div>
                )}
            </CardContent>
        </Card>
    );
}
