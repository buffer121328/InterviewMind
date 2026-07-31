import type { EvaluationExternalIo } from '@/lib/api/evaluations';

/** 展示外部依赖的计数、耗时和稳定错误分类，不显示 query、URL 或响应正文。 */
export function ExternalIoCard({ item }: { item: EvaluationExternalIo }) {
    return <div className="rounded-lg border bg-white p-3 text-xs">
        <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-semibold text-slate-800">External IO · {item.operation}</span>
            <span className={`rounded-full px-2 py-0.5 ${item.status === 'completed' ? 'bg-emerald-50 text-emerald-700' : item.status === 'failed' ? 'bg-red-50 text-red-700' : 'bg-blue-50 text-blue-700'}`}>{item.status}</span>
        </div>
        <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-500">
            {item.dependency && <span>依赖: {item.dependency}</span>}<span>attempt: {item.attempt}</span>
            {item.result_count != null && <span>结果: {item.result_count}</span>}
            {item.duration_ms != null && <span>{item.duration_ms} ms</span>}
        </div>
        {(item.error_category || item.error_type) && <div className="mt-2 rounded-md bg-red-50 px-2 py-1 text-red-700">错误: {item.error_category ?? item.error_type}</div>}
    </div>;
}
