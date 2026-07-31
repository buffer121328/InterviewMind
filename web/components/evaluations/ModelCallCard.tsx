import type { EvaluationModelCall } from '@/lib/api/evaluations';

/** 展示模型路由与耗时摘要，不显示 prompt、输入或模型输出。 */
export function ModelCallCard({ call }: { call: EvaluationModelCall }) {
    return <div className="rounded-lg border bg-white p-3 text-xs">
        <div className="flex flex-wrap items-center justify-between gap-2"><span className="font-semibold text-slate-800">Model · {call.model_channel}</span><span className="text-slate-500">{call.status}</span></div>
        <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-500"><span>fallback: {call.fallback_index}</span><span>{call.latency_ms} ms</span><span>member: {call.model_member_hash.slice(0, 16)}…</span></div>
        {call.error_classification && <div className="mt-2 rounded-md bg-red-50 px-2 py-1 text-red-700">错误: {call.error_classification}</div>}
    </div>;
}
