import type { EvaluationApproval } from '@/lib/api/evaluations';

/** 展示审批状态与证据引用，避免把 actor hash 或审批正文暴露到页面。 */
export function ApprovalEvidenceCard({ approval }: { approval: EvaluationApproval }) {
    return <div className="rounded-lg border bg-white p-3 text-xs">
        <div className="flex flex-wrap items-center justify-between gap-2"><span className="font-semibold text-slate-800">Approval · {approval.action}</span><span className={`rounded-full px-2 py-0.5 ${approval.status === 'approved' ? 'bg-emerald-50 text-emerald-700' : approval.status === 'rejected' ? 'bg-red-50 text-red-700' : 'bg-amber-50 text-amber-700'}`}>{approval.status}</span></div>
        {approval.evidence_refs.length > 0 && <div className="mt-2 text-[11px] text-slate-500">证据: {approval.evidence_refs.join(', ')}</div>}
    </div>;
}
