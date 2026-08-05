'use client';

import { useEffect, useState } from 'react';
import { BriefcaseBusiness, Loader2, MapPin } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog';
import { getJobDetail, listJobs, type JobListItem } from '@/lib/api/jobs';
import { buildInterviewJobSelection, type InterviewJobSelection } from '@/lib/interviewJobSelection';
import { cn } from '@/lib/utils';

interface JobLibraryPickerDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    onSelect: (selection: InterviewJobSelection) => void;
    onOpenJobLibrary?: () => void;
}

/** Loads owner-scoped job records and returns one verified detail as editable interview context. */
export function JobLibraryPickerDialog({
    open,
    onOpenChange,
    onSelect,
    onOpenJobLibrary,
}: JobLibraryPickerDialogProps) {
    const [jobs, setJobs] = useState<JobListItem[]>([]);
    const [selectedId, setSelectedId] = useState<number | null>(null);
    const [loading, setLoading] = useState(false);
    const [confirming, setConfirming] = useState(false);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (!open) return;
        let cancelled = false;
        void Promise.resolve().then(() => {
            if (cancelled) return;
            setLoading(true);
            setError(null);
            return listJobs({ limit: 50, offset: 0 })
                .then(response => {
                    if (cancelled) return;
                    setJobs(response.jobs);
                    setSelectedId(current => current && response.jobs.some(job => job.id === current)
                        ? current
                        : response.jobs[0]?.id ?? null);
                })
                .catch(reason => {
                    if (!cancelled) setError(reason instanceof Error ? reason.message : '岗位库加载失败');
                })
                .finally(() => {
                    if (!cancelled) setLoading(false);
                });
        });
        return () => { cancelled = true; };
    }, [open]);

    /** Loads the selected owner-scoped detail before constructing the interview handoff. */
    async function confirmSelection(): Promise<void> {
        if (selectedId == null) return;
        setConfirming(true);
        setError(null);
        try {
            const response = await getJobDetail(selectedId);
            onSelect(buildInterviewJobSelection(response.job));
            onOpenChange(false);
        } catch (reason) {
            setError(reason instanceof Error ? reason.message : '岗位详情加载失败');
        } finally {
            setConfirming(false);
        }
    }

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-[680px]">
                <DialogHeader>
                    <DialogTitle>从岗位库选择</DialogTitle>
                    <DialogDescription>选择一条已入库岗位，只导入当前岗位资料，不会启动模型或创建任务。</DialogDescription>
                </DialogHeader>
                <div className="max-h-[420px] space-y-2 overflow-y-auto py-2 pr-1">
                    {loading ? (
                        <div className="flex items-center justify-center gap-2 py-16 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" />正在加载岗位库…</div>
                    ) : error ? (
                        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>
                    ) : jobs.length === 0 ? (
                        <div className="rounded-xl border border-dashed border-slate-300 p-8 text-center">
                            <BriefcaseBusiness className="mx-auto h-8 w-8 text-slate-300" />
                            <p className="mt-3 text-sm font-medium text-slate-700">岗位库还是空的</p>
                            <p className="mt-1 text-xs text-slate-500">可以先去岗位库导入岗位，也可以关闭后继续手动填写 JD。</p>
                            {onOpenJobLibrary && <Button className="mt-4" variant="outline" onClick={() => { onOpenChange(false); onOpenJobLibrary(); }}>前往岗位库</Button>}
                        </div>
                    ) : jobs.map(job => (
                        <button
                            key={job.id}
                            type="button"
                            onClick={() => setSelectedId(job.id)}
                            className={cn(
                                'w-full rounded-xl border p-4 text-left transition',
                                selectedId === job.id ? 'border-teal-500 bg-teal-50 ring-2 ring-teal-100' : 'border-slate-200 bg-white hover:border-teal-200',
                            )}
                        >
                            <div className="flex items-start justify-between gap-4">
                                <div className="min-w-0">
                                    <p className="font-medium text-slate-900">{job.job_title}</p>
                                    <p className="mt-1 text-sm text-slate-600">{job.company_name}</p>
                                </div>
                                {job.salary_text && <span className="shrink-0 text-sm font-semibold text-teal-700">{job.salary_text}</span>}
                            </div>
                            <div className="mt-2 flex flex-wrap gap-3 text-xs text-slate-500">
                                {job.city && <span className="inline-flex items-center gap-1"><MapPin className="h-3 w-3" />{job.city}</span>}
                                {job.company_size_text && <span>{job.company_size_text}</span>}
                                <span>{job.platform || '岗位库'}</span>
                            </div>
                        </button>
                    ))}
                </div>
                <DialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)}>取消</Button>
                    <Button onClick={() => void confirmSelection()} disabled={selectedId == null || loading || confirming} className="bg-teal-600 hover:bg-teal-700">
                        {confirming && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                        导入模拟面试
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
