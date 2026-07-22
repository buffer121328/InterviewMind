/**
 * API 配置公共模块
 * 统一管理 API 基础 URL 和请求工具
 */

export const USER_ID_KEY = 'interview_ai_user_id';
export const USER_ID_CHANGED_EVENT = 'interview-ai-user-id-changed';

/**
 * 规范化 API 基础地址。
 *
 * 后端路由自身已经以 /api 开头；Docker/Nginx 部署时 NEXT_PUBLIC_API_URL
 * 常配置为 /api。如果直接拼接会变成 /api/api/...，因此这里统一把末尾
 * 的 /api 作为代理前缀剥离，让调用方继续使用后端契约路径。
 */
export function normalizeApiBaseUrl(rawBaseUrl: string | undefined): string {
    const fallback = 'http://localhost:8000';
    const trimmed = (rawBaseUrl || fallback).trim().replace(/\/+$/, '');

    if (trimmed === '/api') return '';
    if (trimmed.endsWith('/api')) {
        return trimmed.slice(0, -'/api'.length);
    }

    return trimmed;
}

export const API_BASE_URL = normalizeApiBaseUrl(process.env.NEXT_PUBLIC_API_URL);

export function buildApiUrl(url: string): string {
    if (/^https?:\/\//i.test(url)) return url;
    const path = url.startsWith('/') ? url : `/${url}`;
    return `${API_BASE_URL}${path}`;
}


function getErrorMessage(error: unknown, fallback: string): string {
    if (typeof error === 'string') return error;
    if (error && typeof error === 'object') {
        const record = error as Record<string, unknown>;
        if (typeof record.message === 'string') return record.message;
        if (typeof record.error === 'string') return record.error;
    }
    return fallback;
}

function createUserId(): string {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
        return crypto.randomUUID();
    }
    return `user_${Date.now()}_${Math.random().toString(36).slice(2)}`;
}

/**
 * 获取用户 ID（从 localStorage）；不存在时自动生成，确保所有 API 请求都带真实用户隔离头。
 */
export function getUserId(): string {
    if (typeof window === 'undefined') return 'default_user';

    let userId = localStorage.getItem(USER_ID_KEY);
    if (!userId) {
        userId = createUserId();
        localStorage.setItem(USER_ID_KEY, userId);
    }
    return userId;
}


/**
 * 统一的 API 请求处理
 */
export async function apiRequest<T>(
    url: string,
    options?: RequestInit
): Promise<T> {
    const userId = getUserId();

    const response = await fetch(buildApiUrl(url), {
        ...options,
        headers: {
            'Content-Type': 'application/json',
            'X-User-ID': userId,
            ...options?.headers,
        },
    });

    if (!response.ok) {
        const error = await response.json().catch(() => ({ message: `HTTP ${response.status}` }));
        const detail = error && typeof error === 'object' && 'detail' in error
            ? (error as { detail?: unknown }).detail
            : undefined;
        throw new Error(getErrorMessage(detail, getErrorMessage(error, `HTTP ${response.status}`)));
    }

    return response.json();
}

/**
 * 带认证的 fetch（不解析响应，用于流式请求等）
 */
export async function authFetch(
    url: string,
    options?: RequestInit
): Promise<Response> {
    const userId = getUserId();

    return fetch(buildApiUrl(url), {
        ...options,
        headers: {
            'X-User-ID': userId,
            ...options?.headers,
        },
    });
}
