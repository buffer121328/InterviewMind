'use client';

import { useMemo, useState } from 'react';
import { ArrowRight, ChevronDown, ChevronUp } from 'lucide-react';

import { PaginationControls } from '@/components/PaginationControls';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import type { EvaluationCatalog, EvaluationRun } from '@/lib/api/evaluations';
import { formatChinaDateTime } from '@/lib/chinaTime';
import {
    evaluationBatchStatus,
    evaluationRunModeLabel,
    recentEvaluationResultItems,
    recentEvaluationResultPage,
    RECENT_EVALUATION_PAGE_SIZE,
    type RecentEvaluationResultItem,
} from '@/lib/recentEvaluationResults';

interface RecentEvaluationResultsProps {
    catalog: EvaluationCatalog;
    runs: EvaluationRun[];
    selectedAgentName: string | null;
    loading: boolean;
    onRefresh: () => Promise<void>;
    onOpenRun: (runId: string) => void;
}

/** Renders the ten most recent top-level records, grouping all-agent smoke batches into one disclosure. */
export function RecentEvaluationResults({
    catalog,
    runs,
    selectedAgentName,
    loading,
    onRefresh,
    onOpenRun,
}: RecentEvaluationResultsProps) {
    const [page, setPage] = useState(1);
    const [expandedBatchIds, setExpandedBatchIds] = useState<Set<string>>(() => new Set());
    const items = useMemo(
        () => recentEvaluationResultItems(runs, selectedAgentName),
        [runs, selectedAgentName],
    );
    const totalPages = Math.max(1, Math.ceil(items.length / RECENT_EVALUATION_PAGE_SIZE));
    const activePage = Math.min(page, totalPages);
    const pageItems = useMemo(() => recentEvaluationResultPage(items, activePage), [items, activePage]);

    function toggleBatch(batchId: string): void {
        setExpandedBatchIds(current => {
            const next = new Set(current);
            if (next.has(batchId)) next.delete(batchId); else next.add(batchId);
            return next;
        });
    }

    return <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
                <h3 className="font-semibold text-slate-900">最近结果</h3>
                <p className="mt-1 text-xs text-slate-500">最近 10 项按每页 5 项展示；一键全 Agent 冒烟批次按一个可展开项目计数。</p>
            </div>
            <Button variant="ghost" size="sm" onClick={() => void onRefresh()} disabled={loading}>刷新</Button>
        </div>
        <div className="mt-4 space-y-2">
            {loading && items.length === 0 && <Empty text="正在加载最近结果…" />}
            {!loading && items.length === 0 && <Empty text="还没有运行记录，选择上方模式开始第一次评测。" />}
            {pageItems.map(item => item.kind === 'batch'
                ? <SmokeBatchItem
                    key={item.id}
                    item={item}
                    catalog={catalog}
                    expanded={expandedBatchIds.has(item.batchId)}
                    onToggle={toggleBatch}
                    onOpenRun={onOpenRun}
                />
                : <RunItem key={item.id} run={item.run} catalog={catalog} onOpenRun={onOpenRun} />,
            )}
        </div>
        {items.length > RECENT_EVALUATION_PAGE_SIZE && <PaginationControls
            className="mt-4 border-t border-slate-100 pt-4"
            page={activePage}
            total={items.length}
            pageSize={RECENT_EVALUATION_PAGE_SIZE}
            onPageChange={nextPage => setPage(Math.min(nextPage, totalPages))}
            loading={loading}
        />}
    </section>;
}

function SmokeBatchItem({
    item,
    catalog,
    expanded,
    onToggle,
    onOpenRun,
}: {
    item: Extract<RecentEvaluationResultItem, { kind: 'batch' }>;
    catalog: EvaluationCatalog;
    expanded: boolean;
    onToggle: (batchId: string) => void;
    onOpenRun: (runId: string) => void;
}) {
    const status = evaluationBatchStatus(item.runs);
    const disclosureId = `evaluation-smoke-batch-${item.batchId.replace(/[^a-zA-Z0-9_-]/g, '-')}`;

    return <div className="overflow-hidden rounded-xl border border-teal-200 bg-teal-50/30">
        <button
            type="button"
            aria-expanded={expanded}
            aria-controls={disclosureId}
            onClick={() => onToggle(item.batchId)}
            className="flex w-full flex-col gap-3 px-4 py-3 text-left transition hover:bg-teal-50 sm:flex-row sm:items-center sm:justify-between"
        >
            <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-slate-800">一键全 Agent 冒烟</span>
                    <ModeBadge label="快速冒烟" />
                    <StatusBadge status={status} />
                    <Badge variant="outline">{item.runs.length} 个 Agent</Badge>
                </div>
                <p className="mt-1 text-xs text-slate-500">{formatChinaDateTime(item.runs[0]?.created_at ?? '')} · 展开查看各 Agent 结果</p>
            </div>
            <span className="flex shrink-0 items-center gap-2 text-sm font-medium text-teal-800">
                {expanded ? '收起' : '展开'}
                {expanded ? <ChevronUp className="h-4 w-4" aria-hidden="true" /> : <ChevronDown className="h-4 w-4" aria-hidden="true" />}
            </span>
        </button>
        {expanded && <div id={disclosureId} className="max-h-[28rem] space-y-2 overflow-y-auto border-t border-teal-100 bg-white p-3">
            {item.runs.map(run => <RunItem key={run.id} run={run} catalog={catalog} onOpenRun={onOpenRun} compact />)}
        </div>}
    </div>;
}

function RunItem({ run, catalog, onOpenRun, compact = false }: { run: EvaluationRun; catalog: EvaluationCatalog; onOpenRun: (runId: string) => void; compact?: boolean }) {
    return <div className={`flex flex-col gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 sm:flex-row sm:items-center sm:justify-between ${compact ? 'shadow-none' : ''}`}>
        <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-slate-800">{agentLabel(catalog, run.agent_name)}</span>
                <ModeBadge label={evaluationRunModeLabel(run)} />
                <StatusBadge status={run.status} />
                {run.include_judges && <Badge variant="outline">DeepEval Judge</Badge>}
            </div>
            <p className="mt-1 truncate text-xs text-slate-500">{shortId(run.id)} · {formatChinaDateTime(run.created_at)} · 完全成功率 {formatRate(run.summary.complete_success_rate)}</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => onOpenRun(run.id)}>
            查看详情 <ArrowRight className="ml-2 h-3.5 w-3.5" />
        </Button>
    </div>;
}

function Empty({ text }: { text: string }) { return <div className="rounded-xl border border-dashed border-slate-200 p-6 text-center text-sm text-slate-500">{text}</div>; }
function ModeBadge({ label }: { label: string }) { return <Badge variant="outline" className="border-indigo-200 bg-indigo-50 text-indigo-700">{label}</Badge>; }
function StatusBadge({ status }: { status: string }) { return <Badge variant="outline" className={statusClass(status)}>{statusLabel(status)}</Badge>; }
function agentLabel(catalog: EvaluationCatalog, agentName: string): string { return catalog.agents.find(agent => agent.name === agentName)?.label ?? agentName; }
function statusLabel(status: string): string { return ({ queued: '排队中', running: '运行中', succeeded: '已完成', failed: '失败', cancelled: '已取消' } as Record<string, string>)[status] ?? status; }
function statusClass(status: string): string { if (status === 'succeeded') return 'border-emerald-200 bg-emerald-50 text-emerald-700'; if (status === 'failed') return 'border-red-200 bg-red-50 text-red-700'; if (status === 'running') return 'border-blue-200 bg-blue-50 text-blue-700'; return 'border-slate-200 bg-slate-50 text-slate-600'; }
function formatRate(value: unknown): string { const number = Number(value); return value == null || !Number.isFinite(number) ? '-' : `${(number * 100).toFixed(1)}%`; }
function shortId(value: string): string { return value.length > 18 ? `${value.slice(0, 9)}…${value.slice(-6)}` : value; }
