/**
 * 长期记忆管理 API 接口
 *
 * 对应后端 backend/app/api/memory.py，路径前缀 /api/memory
 *
 * 主要功能：
 * 1. 查看当前用户全部 mem0 记忆
 * 2. 搜索记忆（语义检索）
 * 3. 查看单条记忆的变更历史
 * 4. 删除单条 / 清空全部记忆
 */

import { apiRequest } from './config';

// ============================================================================
// 类型定义
// ============================================================================

export interface MemoryItem {
    id: string;
    memory: string;
    metadata?: Record<string, unknown>;
    score?: number;
    created_at?: string;
    updated_at?: string;
}

export interface MemoryListResponse {
    success: boolean;
    memories: MemoryItem[];
    total: number;
    user_id?: string;
    message?: string; // 如 "mem0 未启用"
}

export interface MemorySearchResponse {
    success: boolean;
    memories: MemoryItem[];
    query: string;
    total: number;
    message?: string;
}

export interface MemoryHistoryItem {
    id: string;
    memory_id: string;
    event: string; // "ADD" | "UPDATE" | "DELETE"
    old_memory?: string;
    new_memory?: string;
    created_at?: string;
}

export interface MemoryHistoryResponse {
    success: boolean;
    history: MemoryHistoryItem[];
    memory_id: string;
    message?: string;
}

export interface MemoryDeleteResponse {
    success: boolean;
    message: string;
    memory_id?: string;
}

export interface MemoryDeleteAllRequest {
    confirm: boolean;
}

export interface MemoryDeleteAllResponse {
    success: boolean;
    message: string;
}

// ============================================================================
// API 调用
// ============================================================================

/**
 * 获取当前用户全部记忆
 * GET /api/memory?page_size=100
 */
export async function getAllMemories(pageSize = 100): Promise<MemoryListResponse> {
    return apiRequest<MemoryListResponse>(`/api/memory?page_size=${pageSize}`);
}

/**
 * 搜索记忆（语义检索）
 * GET /api/memory/search?q=xxx&limit=5&memory_type=interview_preference
 */
export async function searchMemories(params: {
    q: string;
    limit?: number;
    memory_type?: string;
}): Promise<MemorySearchResponse> {
    const query = new URLSearchParams({ q: params.q });
    if (params.limit != null) query.set('limit', String(params.limit));
    if (params.memory_type) query.set('memory_type', params.memory_type);
    return apiRequest<MemorySearchResponse>(`/api/memory/search?${query.toString()}`);
}

/**
 * 查看单条记忆变更历史
 * GET /api/memory/{memory_id}/history
 */
export async function getMemoryHistory(memoryId: string): Promise<MemoryHistoryResponse> {
    return apiRequest<MemoryHistoryResponse>(`/api/memory/${encodeURIComponent(memoryId)}/history`);
}

/**
 * 删除单条记忆
 * DELETE /api/memory/{memory_id}
 */
export async function deleteMemory(memoryId: string): Promise<MemoryDeleteResponse> {
    return apiRequest<MemoryDeleteResponse>(`/api/memory/${encodeURIComponent(memoryId)}`, {
        method: 'DELETE',
    });
}

/**
 * 清空全部记忆（必须传 confirm=true 才执行）
 * DELETE /api/memory   body: { confirm: true }
 */
export async function deleteAllMemories(confirm = true): Promise<MemoryDeleteAllResponse> {
    return apiRequest<MemoryDeleteAllResponse>('/api/memory', {
        method: 'DELETE',
        body: JSON.stringify({ confirm }),
    });
}