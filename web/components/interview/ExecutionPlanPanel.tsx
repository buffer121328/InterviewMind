import { CheckCircle2, Circle, Loader2, XCircle } from "lucide-react";
import type { ExecutionPlanStep } from "@/store/types";
import { cn } from "@/lib/utils";

interface ExecutionPlanPanelProps {
    steps: ExecutionPlanStep[];
    className?: string;
    dark?: boolean;
}

export function ExecutionPlanPanel({ steps, className, dark = false }: ExecutionPlanPanelProps) {
    if (steps.length === 0) return null;

    return (
        <div className={cn(
            "w-full max-w-md rounded-xl border p-3 text-left",
            dark ? "border-white/10 bg-white/5" : "border-gray-200 bg-white/80 shadow-sm",
            className,
        )}>
            <div className={cn("mb-2 text-xs font-semibold", dark ? "text-white/70" : "text-gray-500")}>
                执行计划
            </div>
            <div className="space-y-2">
                {steps.map((step) => (
                    <div key={step.id} className="flex items-center gap-2 text-sm">
                        {step.status === 'completed' && <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-500" />}
                        {step.status === 'running' && <Loader2 className="h-4 w-4 shrink-0 animate-spin text-orange-500" />}
                        {step.status === 'failed' && <XCircle className="h-4 w-4 shrink-0 text-red-500" />}
                        {step.status === 'pending' && <Circle className={cn("h-4 w-4 shrink-0", dark ? "text-white/25" : "text-gray-300")} />}
                        <span className={cn(
                            step.status === 'running' && "font-medium",
                            step.status === 'completed' && (dark ? "text-white/45" : "text-gray-400"),
                            step.status === 'pending' && (dark ? "text-white/35" : "text-gray-400"),
                            step.status === 'failed' && "text-red-600",
                            step.status === 'running' && (dark ? "text-white" : "text-gray-700"),
                        )}>
                            {step.title}
                        </span>
                    </div>
                ))}
            </div>
        </div>
    );
}
