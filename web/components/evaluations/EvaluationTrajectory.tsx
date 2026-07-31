import type { ReactNode } from 'react';
import type { EvaluationRecord, EvaluationScore } from '@/lib/api/evaluations';
import { ApprovalEvidenceCard } from './ApprovalEvidenceCard';
import { ExternalIoCard } from './ExternalIoCard';
import { ModelCallCard } from './ModelCallCard';
import { RetrievalCard } from './RetrievalCard';
import { ToolCallCard } from './ToolCallCard';

interface Props {
    record: EvaluationRecord;
    scores: EvaluationScore[];
}

interface TimelineNode {
    id: string;
    sequence: number;
    kind: 'tool' | 'retrieval' | 'external' | 'model' | 'approval' | 'runtime';
    content: ReactNode;
}

/**
 * 将统一评测轨迹投影为安全时间线。
 * 历史 record 缺字段时只渲染可用节点，绝不通过非空断言伪造完整性。
 */
export function EvaluationTrajectory({ record, scores }: Props) {
    const hardGateEvidenceRefs = new Set(scores.filter((score) => score.hard_gate && score.status !== 'passed').flatMap((score) => score.evidence_refs));
    const nodes: TimelineNode[] = [
        ...(record.tool_calls ?? []).map((call) => ({ id: `tool-${call.call_id}`, sequence: call.sequence, kind: 'tool' as const, content: <ToolCallCard call={call} hardGateEvidenceRefs={hardGateEvidenceRefs} downstreamExternalIoCount={(record.external_ios ?? []).filter((item) => item.parent_call_id === call.call_id).length} /> })),
        ...(record.retrievals ?? []).map((item) => ({ id: `retrieval-${item.retrieval_id}`, sequence: item.sequence ?? 0, kind: 'retrieval' as const, content: <RetrievalCard item={item} /> })),
        ...(record.external_ios ?? []).map((item) => ({ id: `io-${item.call_id}`, sequence: item.sequence, kind: 'external' as const, content: <ExternalIoCard item={item} /> })),
        ...(record.model_calls ?? []).map((call) => ({ id: `model-${call.call_id}`, sequence: call.sequence, kind: 'model' as const, content: <ModelCallCard call={call} /> })),
        ...(record.approvals ?? []).map((approval) => ({ id: `approval-${approval.approval_id}`, sequence: approval.sequence ?? approval.requested_sequence ?? 0, kind: 'approval' as const, content: <ApprovalEvidenceCard approval={approval} /> })),
        ...(record.events ?? []).filter((event) => !event.event_type.startsWith('tool.') && !event.event_type.startsWith('external_io.') && !event.event_type.startsWith('approval.')).map((event) => ({ id: `event-${event.sequence}-${event.event_type}`, sequence: event.sequence, kind: 'runtime' as const, content: <div className="rounded-lg border bg-white p-3 text-xs"><div className="font-semibold text-slate-800">AgentRun · {event.event_type}</div><div className="mt-1 text-[11px] text-slate-500">{event.stage} · {event.status ?? '记录'}</div></div> })),
    ].sort((left, right) => left.sequence - right.sequence);
    const completeness = record.observability?.trace_completeness;
    return <section className="space-y-3 rounded-xl border border-slate-200 bg-slate-50/70 p-3" aria-label="评测执行轨迹">
        <div className="flex flex-wrap items-center justify-between gap-2"><div><h5 className="text-sm font-semibold text-slate-800">结构化执行轨迹</h5><p className="text-[11px] text-slate-500">仅显示安全元数据；原始参数、结果、查询、简历、JD 和 Cookie 不进入该组件。</p></div>{completeness && <span className={`rounded-full px-2 py-1 text-[11px] ${completeness.complete ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>{completeness.complete ? 'Trace 完整' : `观测缺失 ${completeness.missing.join(', ') || '未知'}`}</span>}</div>
        {record.observability?.langfuse_reported === false && <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">本地证据可用，远端 Trace/Score 上报降级：{record.observability.langfuse_error ?? 'Langfuse 暂不可用'}。</div>}
        {hardGateEvidenceRefs.size > 0 && <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">硬门禁证据已定位到具体 Tool/Approval 节点。</div>}
        {nodes.length > 0 ? <div className="space-y-2">{nodes.map((node) => <div key={node.id} className="grid grid-cols-[44px_1fr] gap-2"><div className="pt-3 text-right text-[10px] text-slate-400">#{node.sequence}</div>{node.content}</div>)}</div> : <div className="rounded-lg border border-dashed bg-white p-4 text-xs text-slate-500">历史运行没有结构化轨迹；可查看下方兼容摘要。</div>}
    </section>;
}
