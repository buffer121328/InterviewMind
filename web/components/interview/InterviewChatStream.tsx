import type { RefObject, UIEventHandler } from "react";
import { Bot } from "lucide-react";

import { ChatMessage } from "@/components/ChatMessage";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { ExecutionPlanStep, Message } from "@/store/types";
import { ExecutionPlanPanel } from "./ExecutionPlanPanel";
import { PreparingInterview } from "./PreparingInterview";

interface InterviewChatStreamProps {
    messages: Message[];
    isLoading: boolean;
    isStreaming: boolean;
    initializationStage: string | null;
    executionPlan: ExecutionPlanStep[];
    viewportRef: RefObject<HTMLDivElement | null>;
    messagesEndRef: RefObject<HTMLDivElement | null>;
    onScroll: UIEventHandler<HTMLDivElement>;
    onEditMessage: (index: number, content: string) => void | Promise<void>;
    onRegenerateMessage: (index: number) => void | Promise<void>;
}

/** Renders the scrollable interview transcript and its loading/thinking states. */
export function InterviewChatStream({
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
}: InterviewChatStreamProps) {
    const lastMessage = messages.at(-1);

    return (
        <ScrollArea className="flex-1 overflow-hidden px-4" viewportRef={viewportRef} onScroll={onScroll}>
            <div className="mx-auto max-w-5xl space-y-6 pb-2 pt-6">
                {(isLoading || isStreaming) && messages.length === 0 && (
                    <PreparingInterview stage={initializationStage} plan={executionPlan} />
                )}

                {messages.map((message, index) => (
                    <ChatMessage
                        key={index}
                        role={message.role}
                        content={message.content}
                        timestamp={message.timestamp}
                        onEdit={message.role === "user" ? (content) => onEditMessage(index, content) : undefined}
                        onRegenerate={message.role === "assistant" && index !== 0 ? () => onRegenerateMessage(index) : undefined}
                    />
                ))}

                {isStreaming && lastMessage?.role === "user" && (
                    <div className="space-y-3 px-4">
                        <div className="flex animate-pulse items-center gap-2 text-sm text-gray-400">
                            <Bot className="h-4 w-4" />
                            <span>面试官正在思考...</span>
                        </div>
                        <ExecutionPlanPanel steps={executionPlan} />
                    </div>
                )}
                <div ref={messagesEndRef} />
            </div>
        </ScrollArea>
    );
}
