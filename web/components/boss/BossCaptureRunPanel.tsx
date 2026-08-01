'use client';

import { AlertTriangle, CheckCircle2, Loader2 } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { getAgentRunStatusLabel } from '@/lib/agentRunDisplayGroups';
import type { AgentRun } from '@/lib/api/agentRunTypes';
import { captureRunMessage } from '@/lib/bossCenter';

interface BossCaptureRunPanelProps {
    captureRun: AgentRun;
    captureElapsed: number;
}

/** Renders the current capture AgentRun progress, plan steps and failures without exposing browser credentials. */
export function BossCaptureRunPanel({ captureRun, captureElapsed }: BossCaptureRunPanelProps) {
    return (
        <div className={`surface-panel border p-4 ${captureRun.status === "failed" ? "border-red-200" : "border-slate-200"}`}>
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                    <div className="text-sm font-semibold text-slate-900">{captureRun.title}</div>
                    <p className="mt-1 text-xs text-slate-500">{captureRunMessage(captureRun, captureElapsed)}</p>
                    {captureRun.error_message && <p className="mt-2 text-xs text-red-700">{captureRun.error_message}</p>}
                </div>
                <Badge variant="outline">{getAgentRunStatusLabel(captureRun)}</Badge>
            </div>
            <ol className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
                {captureRun.plan.map(step => (
                    <li key={step.id} className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs ${
                        step.status === "completed"
                            ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                            : step.status === "running"
                                ? "border-teal-200 bg-teal-50 text-teal-800"
                                : step.status === "failed"
                                    ? "border-red-200 bg-red-50 text-red-800"
                                    : "border-slate-200 bg-slate-50 text-slate-500"
                    }`}>
                        {step.status === "running" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                        {step.status === "completed" && <CheckCircle2 className="h-3.5 w-3.5" />}
                        {step.status === "failed" && <AlertTriangle className="h-3.5 w-3.5" />}
                        {step.status === "pending" && <span className="h-2 w-2 rounded-full bg-slate-300" />}
                        {step.title}
                    </li>
                ))}
            </ol>
        </div>
    );
}
