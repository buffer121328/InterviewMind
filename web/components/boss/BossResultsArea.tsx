'use client';

import { CheckCircle2, Sparkles } from 'lucide-react';

import type { AgentRun } from '@/lib/api/agentRunTypes';
import type { CapturedJobSummary } from '@/lib/api/jobs';
import { BossResultCard } from '@/components/boss/BossResultCard';

interface BossResultsAreaProps {
    results: CapturedJobSummary[];
    captureRun: AgentRun | null;
    actionKey: string | null;
    onDeletePending: (job: CapturedJobSummary) => void;
    onOpenExistingBossTab: (jobId: number) => void;
}

/** Renders the current-import results column: waiting, all-imported, or the card list. */
export function BossResultsArea({
    results,
    captureRun,
    actionKey,
    onDeletePending,
    onOpenExistingBossTab,
}: BossResultsAreaProps) {
    if (results.length === 0 && !captureRun) {
        return (
            <div className="surface-panel flex min-h-72 flex-col items-center justify-center text-center">
                <Sparkles className="h-9 w-9 text-slate-300" />
                <div className="mt-3 text-sm font-medium text-slate-900">等待本次采集结果</div>
                <p className="mt-1 max-w-md text-xs leading-5 text-slate-500">这里会显示岗位、薪资、公司人数、职位介绍和匹配度。</p>
            </div>
        );
    }
    if (results.length === 0 && captureRun?.status === "succeeded") {
        return (
            <div className="surface-panel flex min-h-56 flex-col items-center justify-center text-center">
                <CheckCircle2 className="h-9 w-9 text-emerald-500" />
                <div className="mt-3 text-sm font-medium text-slate-900">本次采集的岗位已全部入库</div>
                <p className="mt-1 max-w-md text-xs leading-5 text-slate-500">可在「岗位库」页签查看岗位详情和匹配度。</p>
            </div>
        );
    }
    return (
        <>
            {results.map(job => (
                <BossResultCard
                    key={job.job_id == null ? (job.source_url || job.job_title) : job.job_id}
                    job={job}
                    actionKey={actionKey}
                    onDeletePending={onDeletePending}
                    onOpenExistingBossTab={onOpenExistingBossTab}
                />
            ))}
        </>
    );
}
