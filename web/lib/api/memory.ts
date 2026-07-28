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
import type { ApiConfig } from './resumeTypes';

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
 * POST /api/memory/list
 */
export async function getAllMemories(apiConfig: ApiConfig, pageSize = 100): Promise<MemoryListResponse> {
    return apiRequest<MemoryListResponse>('/api/memory/list', {
        method: 'POST',
        body: JSON.stringify({ page_size: pageSize, api_config: apiConfig }),
    });
}

/**
 * 搜索记忆（语义检索）
 * POST /api/memory/search
 */
export async function searchMemories(params: {
    q: string;
    limit?: number;
    memory_type?: string;
    api_config: ApiConfig;
}): Promise<MemorySearchResponse> {
    return apiRequest<MemorySearchResponse>('/api/memory/search', {
        method: 'POST',
        body: JSON.stringify({
            query: params.q,
            limit: params.limit,
            memory_type: params.memory_type,
            api_config: params.api_config,
        }),
    });
}

/**
 * 查看单条记忆变更历史
 * POST /api/memory/{memory_id}/history
 */
export async function getMemoryHistory(memoryId: string, apiConfig: ApiConfig): Promise<MemoryHistoryResponse> {
    return apiRequest<MemoryHistoryResponse>(`/api/memory/${encodeURIComponent(memoryId)}/history`, {
        method: 'POST',
        body: JSON.stringify({ api_config: apiConfig }),
    });
}

/**
 * 删除单条记忆
 * DELETE /api/memory/{memory_id}
 */
export async function deleteMemory(memoryId: string, apiConfig: ApiConfig): Promise<MemoryDeleteResponse> {
    return apiRequest<MemoryDeleteResponse>(`/api/memory/${encodeURIComponent(memoryId)}`, {
        method: 'DELETE',
        body: JSON.stringify({ api_config: apiConfig }),
    });
}

/**
 * 清空全部记忆（必须传 confirm=true 才执行）
 * DELETE /api/memory   body: { confirm: true }
 */
export async function deleteAllMemories(apiConfig: ApiConfig, confirm = true): Promise<MemoryDeleteAllResponse> {
    return apiRequest<MemoryDeleteAllResponse>('/api/memory', {
        method: 'DELETE',
        body: JSON.stringify({ confirm, api_config: apiConfig }),
    });
}
