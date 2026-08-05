'use client';

import { useState } from 'react';
import { Activity, AlertTriangle, Gauge, ListTree } from 'lucide-react';
import { TaskRunsTab, type TaskRunsTabProps } from '@/components/run-center/TaskRunsTab';
import { DegradationsTab, ModelCallsTab, PerformanceOverviewTab } from '@/components/run-center/PerformanceTabs';

type RunCenterTab = 'overview' | 'runs' | 'models' | 'degradations';
const TABS: Array<{ id: RunCenterTab; label: string; icon: typeof Gauge }> = [
    { id: 'overview', label: '性能总览', icon: Gauge },
    { id: 'runs', label: '任务运行', icon: ListTree },
    { id: 'models', label: '模型调用', icon: Activity },
    { id: 'degradations', label: '异常与降级', icon: AlertTriangle },
];

/** Coordinates the four Phase 4 performance views while delegating business state to each domain component. */
export function RunCenter(props: TaskRunsTabProps) {
    const [tab, setTab] = useState<RunCenterTab>('overview');
    const [days, setDays] = useState(7);
    return <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6">
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
            <div><h1 className="text-2xl font-semibold text-slate-900">Agent 运行与性能</h1><p className="mt-1 text-sm text-slate-500">本地聚合用于产品验收，完整 Trace 仍由 Langfuse 承载。</p></div>
            {tab !== 'runs' && <select aria-label="性能时间窗口" className="h-10 rounded-lg border bg-white px-3 text-sm" value={days} onChange={event => setDays(Number(event.target.value))}><option value={1}>最近 24 小时</option><option value={7}>最近 7 天</option><option value={30}>最近 30 天</option><option value={90}>最近 90 天</option></select>}
        </div>
        <div className="mb-6 grid gap-2 rounded-xl bg-slate-100 p-1 sm:grid-cols-4">{TABS.map(item => { const Icon = item.icon; return <button key={item.id} type="button" onClick={() => setTab(item.id)} className={`flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-medium ${tab === item.id ? 'bg-white text-teal-700 shadow-sm' : 'text-slate-600 hover:text-slate-900'}`}><Icon className="h-4 w-4" />{item.label}</button>; })}</div>
        {tab === 'overview' && <PerformanceOverviewTab days={days} />}
        {tab === 'runs' && <TaskRunsTab {...props} />}
        {tab === 'models' && <ModelCallsTab days={days} />}
        {tab === 'degradations' && <DegradationsTab days={days} />}
    </div>;
}
