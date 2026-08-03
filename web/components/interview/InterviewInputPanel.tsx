'use client';

import type { KeyboardEventHandler, ReactNode } from 'react';
import { ArrowDown } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { InterviewAnswerComposer } from '@/components/interview/InterviewAnswerComposer';

interface InterviewInputPanelProps {
    showScrollButton: boolean;
    onScrollToBottom: () => void;
    onKeyDown: KeyboardEventHandler<HTMLTextAreaElement>;
    children?: ReactNode;
    // InterviewAnswerComposer 透传属性
    input: string;
    onInputChange: (value: string) => void;
    isStreaming: boolean;
    isListening: boolean;
    isExpanded: boolean;
    isInterviewCompleted: boolean;
    isLoadingHint: boolean;
    canRequestHint: boolean;
    hintContent: string | null;
    onExpandedChange: (expanded: boolean) => void;
    onRequestHint: () => void | Promise<void>;
    onDismissHint: () => void;
    onToggleListening: () => void;
    onSend: () => void | Promise<void>;
    onStopStreaming: () => void;
}

/** Renders the input region: scroll-to-bottom action, optional banner and the answer composer. */
export function InterviewInputPanel({
    showScrollButton,
    onScrollToBottom,
    onKeyDown,
    children,
    input,
    onInputChange,
    isStreaming,
    isListening,
    isExpanded,
    isInterviewCompleted,
    isLoadingHint,
    canRequestHint,
    hintContent,
    onExpandedChange,
    onRequestHint,
    onDismissHint,
    onToggleListening,
    onSend,
    onStopStreaming,
}: InterviewInputPanelProps) {
    return (
        <div className="relative w-full bg-white border-t border-gray-100 px-6 py-4 z-20">
            <div className="relative mx-auto max-w-5xl">
                {/* 滚动到底部按钮 - 移动到输入框上方，确保不被遮挡 */}
                {showScrollButton && (
                    <div className="absolute -top-12 left-0 right-0 flex justify-center z-20 pointer-events-none">
                        <Button
                            size="sm"
                            variant="secondary"
                            className="rounded-full shadow-lg bg-white border border-gray-200 hover:bg-gray-50 text-gray-600 gap-2 pointer-events-auto animate-in fade-in zoom-in duration-300"
                            onClick={onScrollToBottom}
                        >
                            <ArrowDown className="w-4 h-4" />
                            <span>回到底部</span>
                        </Button>
                    </div>
                )}
                {isInterviewCompleted ? (
                    children || (
                        <div className="rounded-xl border border-teal-200 bg-teal-50 px-5 py-4">
                            <h4 className="font-semibold text-teal-900">面试已完成！</h4>
                            <p className="mt-1 text-sm text-teal-700">本轮回答已关闭，请查看评估或继续进行下一轮面试。</p>
                        </div>
                    )
                ) : (
                    <InterviewAnswerComposer
                        input={input}
                        onInputChange={onInputChange}
                        onKeyDown={onKeyDown}
                        isStreaming={isStreaming}
                        isListening={isListening}
                        isExpanded={isExpanded}
                        isInterviewCompleted={false}
                        isLoadingHint={isLoadingHint}
                        canRequestHint={canRequestHint}
                        hintContent={hintContent}
                        onExpandedChange={onExpandedChange}
                        onRequestHint={onRequestHint}
                        onDismissHint={onDismissHint}
                        onToggleListening={onToggleListening}
                        onSend={onSend}
                        onStopStreaming={onStopStreaming}
                    />
                )}
            </div>
        </div>
    );
}
