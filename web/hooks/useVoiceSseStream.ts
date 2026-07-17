import { useCallback } from 'react';
import { parseSseFrames } from '@/lib/sse';
import { parseStreamEvent } from '@/lib/streamEvents';

interface VoiceSseStreamHandlers {
    onText?: (content: string) => void;
    onAudio?: (content: string) => void;
    onProgress?: (current: number, total?: number) => void;
    onComplete?: () => void;
    onDone?: () => void;
    onError?: (message: string) => void;
    onMalformedFrame?: (error: unknown) => void;
}

export function useVoiceSseStream() {
    const readVoiceSseStream = useCallback(async (response: Response, handlers: VoiceSseStreamHandlers) => {
        const reader = response.body?.getReader();
        if (!reader) throw new Error('无法读取响应流');

        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const parsed = parseSseFrames(buffer, decoder.decode(value, { stream: true }));
            buffer = parsed.buffer;

            for (const frame of parsed.frames) {
                try {
                    const event = parseStreamEvent(JSON.parse(frame.data));
                    if (!event) continue;

                    if (event.type === 'text') {
                        handlers.onText?.(event.content);
                    } else if (event.type === 'audio') {
                        handlers.onAudio?.(event.content);
                    } else if (event.type === 'progress') {
                        handlers.onProgress?.(event.current, event.total);
                    } else if (event.type === 'complete') {
                        handlers.onComplete?.();
                    } else if (event.type === 'done') {
                        handlers.onDone?.();
                    } else if (event.type === 'error') {
                        handlers.onError?.(event.content);
                    }
                } catch (error) {
                    handlers.onMalformedFrame?.(error);
                }
            }
        }
    }, []);

    return { readVoiceSseStream };
}
