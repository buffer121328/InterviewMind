import { Mic } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { InterviewProgress } from "@/store/types";

interface InterviewProgressBarProps {
    progress: InterviewProgress | null;
    messageCount: number;
    onSwitchToVoice: () => void | Promise<void>;
}

/** Displays the active interview status and keeps voice switching outside the page-level coordinator. */
export function InterviewProgressBar({ progress, messageCount, onSwitchToVoice }: InterviewProgressBarProps) {
    if (!progress || progress.total <= 0 || messageCount === 0) return null;

    const isCompleted = progress.current >= progress.total;

    return (
        <div className="sticky top-0 z-10 border-b border-gray-100 bg-white/80 backdrop-blur-sm">
            <div className="mx-auto max-w-3xl px-6 py-3">
                <div className="flex items-center justify-between text-sm">
                    <div className="flex items-center gap-2">
                        <div className="flex items-center gap-1.5">
                            <div className={cn(
                                "h-2 w-2 rounded-full",
                                isCompleted ? "bg-gray-400" : "animate-pulse bg-teal-500",
                            )} />
                            <span className="font-medium text-gray-700">
                                {isCompleted ? "面试已完成" : "面试进行中"}
                            </span>
                        </div>
                        <span className="text-gray-300">|</span>
                        <span className="text-gray-500">
                            问题 {Math.min(progress.current + 1, progress.total)} / {progress.total}
                        </span>
                    </div>

                    {!isCompleted && (
                        <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 gap-1.5 px-2 text-purple-700 hover:bg-purple-50 hover:text-purple-800"
                            onClick={onSwitchToVoice}
                        >
                            <Mic className="h-3.5 w-3.5" />
                            <span>切换语音面试</span>
                        </Button>
                    )}
                </div>
                <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-gray-100">
                    <div
                        className="h-full rounded-full bg-teal-500 transition-all duration-500 ease-out"
                        style={{ width: `${(progress.current / progress.total) * 100}%` }}
                    />
                </div>
            </div>
        </div>
    );
}
