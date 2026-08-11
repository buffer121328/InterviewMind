import { Activity, AlertTriangle, Gauge, ListTree, type LucideIcon } from 'lucide-react';

export type RunCenterTab = 'overview' | 'runs' | 'models' | 'degradations';

export const RUN_CENTER_TABS: Array<{ id: RunCenterTab; label: string; icon: LucideIcon }> = [
    { id: 'runs', label: '任务运行', icon: ListTree },
    { id: 'models', label: '模型调用', icon: Activity },
    { id: 'degradations', label: '异常与降级', icon: AlertTriangle },
    { id: 'overview', label: '性能总览（本地模型）', icon: Gauge },
];
