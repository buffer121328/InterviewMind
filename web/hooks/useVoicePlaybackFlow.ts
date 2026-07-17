import { useCallback, useMemo, useRef } from 'react';

export function useVoicePlaybackFlow() {
    const waitingForPlaybackRef = useRef(false);
    const isInterviewEndPendingRef = useRef(false);

    const shouldHoldVadStatus = useCallback(() => isInterviewEndPendingRef.current, []);
    const markWaitingForPlayback = useCallback(() => {
        waitingForPlaybackRef.current = true;
    }, []);
    const consumeWaitingForPlayback = useCallback(() => {
        if (!waitingForPlaybackRef.current) return false;
        waitingForPlaybackRef.current = false;
        return true;
    }, []);
    const markInterviewEndPending = useCallback(() => {
        isInterviewEndPendingRef.current = true;
    }, []);
    const isInterviewEndPending = useCallback(() => isInterviewEndPendingRef.current, []);
    const resetPlaybackFlow = useCallback(() => {
        waitingForPlaybackRef.current = false;
        isInterviewEndPendingRef.current = false;
    }, []);

    return useMemo(() => ({
        shouldHoldVadStatus,
        markWaitingForPlayback,
        consumeWaitingForPlayback,
        markInterviewEndPending,
        isInterviewEndPending,
        resetPlaybackFlow,
    }), [
        shouldHoldVadStatus,
        markWaitingForPlayback,
        consumeWaitingForPlayback,
        markInterviewEndPending,
        isInterviewEndPending,
        resetPlaybackFlow,
    ]);
}
