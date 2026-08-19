/** 已完成面试轮次的满意度弹窗判定。 */

import type { InterviewSession } from '@/store/types';

/**
 * 仅当当前轮次已经完成且浏览器尚未询问时，才显示满意度弹窗。
 * 会话 ID 由调用方用于持久化去重，因此各轮次天然独立。
 */
export function shouldPromptForInterviewSatisfaction(
    session: Pick<InterviewSession, 'session_id' | 'metadata'> | null,
    alreadyAsked: boolean,
): boolean {
    return Boolean(
        session?.session_id
        && session.metadata.status === 'completed'
        && !alreadyAsked,
    );
}
