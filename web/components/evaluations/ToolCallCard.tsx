import type { EvaluationToolCall } from '@/lib/api/evaluations';

interface Props {
    call: EvaluationToolCall;
    hardGateEvidenceRefs: Set<string>;
    downstreamExternalIoCount: number;
}

/** 展示经后端脱敏确认的 Tool 治理事实，不渲染原始参数或结果。 */
export function ToolCallCard({ call, hardGateEvidenceRefs, downstreamExternalIoCount }: Props) {
    const evidence = call.evidence_refs.filter((ref) => hardGateEvidenceRefs.has(ref));
    return <div className="rounded-lg border bg-white p-3 text-xs">
        <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-semibold text-slate-800">Tool · {call.tool_name}</span>
            <span className={`rounded-full px-2 py-0.5 ${call.status === 'completed' ? 'bg-emerald-50 text-emerald-700' : call.status === 'failed' ? 'bg-red-50 text-red-700' : 'bg-amber-50 text-amber-700'}`}>{call.status}</span>
        </div>
        <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-500">
            <span>effect: {call.effect}</span><span>attempt: {call.attempt}</span>
            <span>审批: {call.requires_confirmation ? call.approval_status : '无需确认'}</span>
            <span>{call.simulated ? '模拟' : '真实执行'}</span>
            <span>下游 IO: {downstreamExternalIoCount}</span>
            {call.duration_ms != null && <span>{call.duration_ms} ms</span>}
        </div>
        {(call.error_category || call.error_type) && <div className="mt-2 rounded-md bg-red-50 px-2 py-1 text-red-700">错误: {call.error_category ?? call.error_type}</div>}
        {evidence.length > 0 && <div className="mt-2 rounded-md bg-red-50 px-2 py-1 text-red-700">硬门禁证据: {evidence.join(', ')}</div>}
    </div>;
}
