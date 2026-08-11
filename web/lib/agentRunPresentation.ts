import type { AgentRun, AgentRunEvent, AgentRunStatus } from './api/agentRunTypes';

/** Formats a timestamp for the compact task timeline. */
export function formatAgentRunDate(value?: string | null) { if (!value) return '-'; return new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }); }

/** Formats elapsed AgentRun time without reading task payloads. */
export function formatAgentRunDuration(run: AgentRun) { if (!run.started_at) return '-'; const end = run.finished_at ? new Date(run.finished_at).getTime() : Date.now(); const ms = Math.max(0, end - new Date(run.started_at).getTime()); if (ms < 1000) return `${ms}ms`; if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`; return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1000)}s`; }

/** Formats a real task-level first-token latency while preserving the no-data state. */
export function formatAgentRunFirstTokenDuration(value?: number | null) {
    if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return '暂无数据';
    if (value < 1000) return `${Math.round(value)}ms`;
    return `${(value / 1000).toFixed(1)}s`;
}

/** Maps lifecycle status to the existing semantic color classes. */
export function agentRunStatusClass(status: AgentRunStatus) { if (status === 'succeeded') return 'bg-emerald-50 text-emerald-700'; if (status === 'failed') return 'bg-red-50 text-red-700'; if (status === 'cancelled') return 'bg-slate-100 text-slate-600'; return 'bg-teal-50 text-teal-700'; }

function payloadString(payload: Record<string, unknown>, key: string) { const value = payload[key]; return typeof value === 'string' && value.trim() ? value.trim() : null; }
function payloadNumber(payload: Record<string, unknown>, key: string) { const value = payload[key]; return typeof value === 'number' && Number.isFinite(value) ? value : null; }

/** Converts safe lifecycle/tool/guardrail events into a user-facing timeline row. */
export function presentAgentRunEvent(event: AgentRunEvent): { title: string; detail: string; kind: 'tool' | 'guardrail' | 'lifecycle' } {
    if (event.type === 'tool.execution') { const toolName = payloadString(event.payload, 'tool_name') || '工具调用'; const status = payloadString(event.payload, 'status') || '已记录'; const effect = payloadString(event.payload, 'effect'); const durationMs = payloadNumber(event.payload, 'duration_ms'); return { title: toolName, detail: [status, effect ? `影响：${effect}` : null, durationMs === null ? null : `${durationMs}ms`, payloadString(event.payload, 'error_message')].filter(Boolean).join(' · '), kind: 'tool' }; }
    if (event.type === 'guardrail.input' || event.type === 'guardrail.output') { const allowed = event.payload.allowed === true; const phase = event.type === 'guardrail.input' ? '输入检查' : '输出检查'; return { title: `${phase} · ${allowed ? '通过' : '已拦截'}`, detail: [payloadString(event.payload, 'code'), payloadString(event.payload, 'message')].filter(Boolean).join(' · ') || '已记录安全检查结果', kind: 'guardrail' }; }
    if (event.type === 'run.created') { const promptName = payloadString(event.payload, 'prompt_name'); const promptVersion = payloadString(event.payload, 'prompt_version'); return { title: '任务已创建', detail: promptName ? `Prompt：${promptName}${promptVersion ? `@${promptVersion}` : ''}` : '已写入可恢复任务队列', kind: 'lifecycle' }; }
    const labels: Partial<Record<AgentRunEvent['type'], string>> = { 'run.started': '开始执行', 'run.stage.changed': '执行阶段更新', 'run.completed': '任务完成', 'run.failed': '任务失败', 'run.cancelled': '任务已取消', 'run.cancel.requested': '已请求取消', 'run.retry.requested': '已请求重试', 'run.recovered': '任务已恢复', 'run.requeued': '任务已重新入队' };
    return { title: labels[event.type] || event.type, detail: payloadString(event.payload, 'message') || event.stage || '状态已更新', kind: 'lifecycle' };
}
