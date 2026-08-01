'use client';

import { Loader2, MapPin, RefreshCw, Trash2 } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { PaginationControls } from '@/components/PaginationControls';
import type { JobListItem } from '@/lib/api/jobs';
import { ASSET_STATUS_LABELS, formatDate } from '@/lib/bossCenter';

interface BossLibraryPanelProps {
    jobs: JobListItem[];
    jobsLoading: boolean;
    jobsError: string | null;
    jobsTotal: number;
    jobsPage: number;
    onPageChange: (page: number) => void;
    onRefresh: () => void;
    onOpenDetail: (jobId: number) => void;
    onDelete: (job: JobListItem) => void;
}

/** Renders the imported job library tab with refresh, delete and paging actions. */
export function BossLibraryPanel({
    jobs,
    jobsLoading,
    jobsError,
    jobsTotal,
    jobsPage,
    onPageChange,
    onRefresh,
    onOpenDetail,
    onDelete,
}: BossLibraryPanelProps) {
    return (
        <section className="surface-panel overflow-hidden">
            <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
                <div>
                    <h2 className="text-sm font-semibold">已导入岗位</h2>
                    <p className="mt-1 text-xs text-slate-500">点击岗位查看完整资产、编辑文案并加入投递管理。</p>
                </div>
                <Button variant="outline" size="sm" onClick={() => onRefresh()} disabled={jobsLoading}>
                    {jobsLoading ? <Loader2 className="animate-spin" /> : <RefreshCw />}刷新
                </Button>
            </div>
            {jobsError && <div className="border-b border-red-100 bg-red-50 px-5 py-3 text-xs text-red-700">{jobsError}</div>}
            <div className="divide-y divide-slate-100">
                {!jobsLoading && jobs.length === 0 && <div className="py-16 text-center text-sm text-slate-400">岗位库为空</div>}
                {jobs.map(job => (
                    <div key={job.id} className="flex items-center gap-2 px-3 py-2 hover:bg-slate-50">
                        <button type="button" className="min-w-0 flex-1 rounded-lg px-2 py-2 text-left" onClick={() => void onOpenDetail(job.id)}>
                            <div className="flex flex-wrap items-start justify-between gap-3">
                                <div className="min-w-0">
                                    <div className="truncate text-sm font-medium text-slate-900">{job.job_title}</div>
                                    <div className="mt-1 text-xs text-slate-600">
                                        {job.company_name || "公司未披露"}{job.company_size_text ? ` · ${job.company_size_text}` : ""}
                                    </div>
                                </div>
                                <Badge className="bg-teal-50 text-teal-700 hover:bg-teal-50">
                                    匹配度 {job.match_score != null ? `${job.match_score}%` : "待分析"}
                                </Badge>
                            </div>
                            <div className="mt-2 flex flex-wrap gap-2 text-[10px] text-slate-500">
                                <Badge variant="outline">{job.salary_text || "薪资未披露"}</Badge>
                                {job.city && <span className="inline-flex items-center gap-1"><MapPin className="h-3 w-3" />{job.city}</span>}
                                {job.asset_status && <Badge variant="outline">{ASSET_STATUS_LABELS[job.asset_status] || job.asset_status}</Badge>}
                                <span>{formatDate(job.captured_at)}</span>
                            </div>
                        </button>
                        <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 shrink-0 text-red-500 hover:bg-red-50 hover:text-red-700"
                            onClick={() => void onDelete(job)}
                            aria-label={`删除 ${job.job_title}`}
                        >
                            <Trash2 className="h-4 w-4" />
                        </Button>
                    </div>
                ))}
            </div>
            <PaginationControls
                className="border-t border-slate-100 px-5 py-4"
                page={jobsPage}
                total={jobsTotal}
                loading={jobsLoading}
                onPageChange={onPageChange}
            />
        </section>
    );
}
