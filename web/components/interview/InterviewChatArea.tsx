'use client';

import type { ReactNode, RefObject, UIEventHandler } from 'react';

import { InterviewChatStream } from '@/components/interview/InterviewChatStream';
import type { ExecutionPlanStep, Message } from '@/store/types';

interface InterviewChatAreaProps {
    messages: Message[];
    isLoading: boolean;
    isStreaming: boolean;
    initializationStage: string | null;
    executionPlan: ExecutionPlanStep[];
    viewportRef: RefObject<HTMLDivElement | null>;
    messagesEndRef: RefObject<HTMLDivElement | null>;
    onScroll: UIEventHandler<HTMLDivElement>;
    onEditMessage: (index: number, content: string) => void | Promise<void>;
    onRegenerateMessage: (index: number, reason: string) => void | Promise<void>;
    children: ReactNode;
}

/** Renders the flex chat region hosting the transcript stream and the inline input panel. */
export function InterviewChatArea({
    messages,
    isLoading,
    isStreaming,
    initializationStage,
    executionPlan,
    viewportRef,
    messagesEndRef,
    onScroll,
    onEditMessage,
    onRegenerateMessage,
    children,
}: InterviewChatAreaProps) {
    return (
        <div className="flex-1 overflow-hidden relative flex flex-col">
            <InterviewChatStream
                messages={messages}
                isLoading={isLoading}
                isStreaming={isStreaming}
                initializationStage={initializationStage}
                executionPlan={executionPlan}
                viewportRef={viewportRef}
                messagesEndRef={messagesEndRef}
                onScroll={onScroll}
                onEditMessage={onEditMessage}
                onRegenerateMessage={onRegenerateMessage}
            />
            {children}
        </div>
    );
}
