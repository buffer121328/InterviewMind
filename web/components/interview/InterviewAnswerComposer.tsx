import type { KeyboardEventHandler } from "react";
import { Lightbulb, Loader2, Square, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface InterviewAnswerComposerProps {
    input: string;
    onInputChange: (value: string) => void;
    onKeyDown: KeyboardEventHandler<HTMLTextAreaElement>;
    isStreaming: boolean;
    isListening: boolean;
    isInterviewCompleted: boolean;
    isLoadingHint: boolean;
    canRequestHint: boolean;
    hintContent: string | null;
    onRequestHint: () => void | Promise<void>;
    onDismissHint: () => void;
    onToggleListening: () => void;
    onSend: () => void | Promise<void>;
    onStopStreaming: () => void;
}

/** Owns the answer editor, hint presentation, voice input trigger, and send/stop action. */
export function InterviewAnswerComposer({
    input, onInputChange, onKeyDown, isStreaming, isListening, isInterviewCompleted,
    isLoadingHint, canRequestHint, hintContent, onRequestHint, onDismissHint,
    onToggleListening, onSend, onStopStreaming,
}: InterviewAnswerComposerProps) {
    return (
        <>
            {hintContent && (
                <div className="mb-4 animate-in rounded-xl border border-amber-200 bg-gradient-to-r from-amber-50 to-yellow-50 p-4 fade-in slide-in-from-bottom-2 duration-300">
                    <div className="flex items-start gap-3">
                        <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-amber-100"><Lightbulb className="h-4 w-4 text-amber-600" /></div>
                        <div className="min-w-0 flex-1">
                            <div className="mb-1 flex items-center justify-between"><h4 className="text-sm font-medium text-amber-800">回答提示</h4><button onClick={onDismissHint} className="rounded-full p-1 transition-colors hover:bg-amber-100"><X className="h-4 w-4 text-amber-600" /></button></div>
                            <p className="whitespace-pre-wrap text-sm leading-relaxed text-amber-700">{hintContent}</p>
                        </div>
                    </div>
                </div>
            )}
            <div className="flex items-end gap-2">
                <div className="relative flex flex-1">
                    <textarea value={input} onChange={(event) => onInputChange(event.target.value)} onKeyDown={onKeyDown} placeholder={isInterviewCompleted ? "本轮面试已结束" : "输入您的回答..."} disabled={isStreaming || isInterviewCompleted} className={cn("min-h-[120px] max-h-[200px] w-full resize-none rounded-2xl border border-gray-200 py-3 pl-4 pr-24 focus:border-teal-500 focus:outline-none focus:ring-2 focus:ring-teal-50", isInterviewCompleted && "cursor-not-allowed bg-gray-50 opacity-60")} rows={4} />
                    <button onClick={onRequestHint} disabled={isInterviewCompleted || isLoadingHint || !canRequestHint} title="获取回答提示" className={cn("absolute bottom-3 right-12 rounded-full p-2 transition-colors", isLoadingHint ? "bg-amber-100 text-amber-500" : "text-amber-400 hover:bg-amber-50 hover:text-amber-500", (isInterviewCompleted || !canRequestHint) && "cursor-not-allowed opacity-50")}>{isLoadingHint ? <Loader2 className="h-5 w-5 animate-spin" /> : <Lightbulb className="h-5 w-5" />}</button>
                    <button onClick={onToggleListening} disabled={isInterviewCompleted} className={cn("absolute bottom-3 right-3 rounded-full p-2 transition-colors", isListening ? "animate-pulse bg-red-100 text-red-500" : "text-gray-400 hover:bg-gray-100", isInterviewCompleted && "cursor-not-allowed opacity-50")} title={isListening ? "停止语音输入" : "开始语音输入"}><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" /><path d="M19 10v2a7 7 0 0 1-14 0v-2" /><line x1="12" x2="12" y1="19" y2="22" /></svg></button>
                </div>
                <Button onClick={isStreaming ? onStopStreaming : onSend} disabled={!isStreaming && (!input.trim() || isInterviewCompleted)} className={cn("h-[52px] w-[52px] rounded-2xl transition-all", isStreaming ? "bg-red-500 shadow-lg shadow-red-200 hover:bg-red-600" : input.trim() && !isInterviewCompleted ? "bg-teal-600 shadow-lg shadow-teal-200 hover:bg-teal-700" : "bg-gray-100 text-gray-400")}>{isStreaming ? <Square className="h-5 w-5" fill="currentColor" /> : <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m22 2-7 20-4-9-9-4Z" /><path d="M22 2 11 13" /></svg>}</Button>
            </div>
        </>
    );
}
