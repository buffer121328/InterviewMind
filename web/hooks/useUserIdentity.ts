/**
 * 用户标识管理 Hook
 * 
 * 负责自动生成并持久化用户 UUID，实现同设备数据关联
 */

import { useCallback, useState, useSyncExternalStore } from 'react';
import { getUserId, USER_ID_CHANGED_EVENT, USER_ID_KEY } from '@/lib/api/config';

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

        const newUserId = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
            ? crypto.randomUUID()
            : `user_${Date.now()}_${Math.random().toString(36).slice(2)}`;
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

export { getUserId };
