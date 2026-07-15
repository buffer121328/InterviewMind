/**
 * 用户标识管理 Hook
 * 
 * 负责自动生成并持久化用户 UUID，实现同设备数据关联
 */

import { useCallback, useState, useSyncExternalStore } from 'react';
import { v4 as uuidv4 } from 'uuid';

const USER_ID_KEY = 'interview_ai_user_id';
const USER_ID_CHANGED_EVENT = 'interview-ai-user-id-changed';

function subscribeToUserId(onStoreChange: () => void) {
    window.addEventListener(USER_ID_CHANGED_EVENT, onStoreChange);
    window.addEventListener('storage', onStoreChange);

    return () => {
        window.removeEventListener(USER_ID_CHANGED_EVENT, onStoreChange);
        window.removeEventListener('storage', onStoreChange);
    };
}

function getUserIdSnapshot() {
    return typeof window === 'undefined' ? '' : getUserId();
}

function notifyUserIdChanged() {
    window.dispatchEvent(new Event(USER_ID_CHANGED_EVENT));
}

/**
 * 用户标识管理 Hook
 * 
 * 特性:
 * - 首次访问自动生成 UUID
 * - 存储到 localStorage 持久化
 * - 后续访问自动读取
 * - 支持手动重置（清除数据用）
 */
export function useUserIdentity() {
    const [isCleared, setIsCleared] = useState(false);
    const userId = useSyncExternalStore(
        subscribeToUserId,
        getUserIdSnapshot,
        () => ''
    );
    const visibleUserId = isCleared ? '' : userId;
    const isInitialized = visibleUserId !== '';

    // 重置用户标识（用于测试或清除数据）
    const resetUserId = useCallback(() => {
        if (typeof window === 'undefined') return;

        const newUserId = uuidv4();
        localStorage.setItem(USER_ID_KEY, newUserId);
        setIsCleared(false);
        notifyUserIdChanged();
        console.log('🔄 重置用户标识:', newUserId.substring(0, 8) + '...');

        return newUserId;
    }, []);

    // 清除用户标识（完全登出）
    const clearUserId = useCallback(() => {
        if (typeof window === 'undefined') return;

        localStorage.removeItem(USER_ID_KEY);
        setIsCleared(true);
        console.log('🧹 已清除用户标识');
    }, []);

    return {
        userId: visibleUserId,
        isInitialized,
        resetUserId,
        clearUserId
    };
}

/**
 * 获取当前用户 ID（非 Hook 版本，用于普通函数中）
 * 
 * @returns 当前用户 ID 或生成新的
 */
export function getUserId(): string {
    if (typeof window === 'undefined') return 'default_user';

    let userId = localStorage.getItem(USER_ID_KEY);

    if (!userId) {
        userId = uuidv4();
        localStorage.setItem(USER_ID_KEY, userId);
        console.log('🆕 生成新用户标识:', userId.substring(0, 8) + '...');
    }

    return userId;
}
