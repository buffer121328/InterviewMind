/**
 * 题库 API 接口
 */

import { API_BASE_URL, getUserId } from './config';

// 题库条目
export interface QuestionBankItem {
    id: number;
    user_id: string;
    source_type: 'manual' | 'generated' | 'imported';
    source_id?: string;
    origin_session_id?: string;
    question_text: string;
    reference_answer?: string;
    tags: string[];
    difficulty: 'easy' | 'medium' | 'hard';
    target_skill?: string;
    question_type: 'intro' | 'tech' | 'behavior' | 'system_design';
    is_verified: boolean;
    usage_count: number;
    created_at: string;
    updated_at: string;
}

// 创建请求
export interface QuestionBankCreateRequest {
    question_text: string;
    reference_answer?: string;
    tags?: string[];
    difficulty?: string;
    target_skill?: string;
    question_type?: string;
    source_type?: string;
}

// 列表响应
export interface QuestionBankListResponse {
    success: boolean;
    items: QuestionBankItem[];
    total: number;
    message?: string;
}

// 导入请求
export interface QuestionBankImportRequest {
    questions: Array<{
        question_text?: string;
        content?: string;
        reference_answer?: string;
        tags?: string[];
        difficulty?: string;
        target_skill?: string;
        question_type?: string;
    }>;
    import_source?: string;
}

// 导入响应
export interface QuestionBankImportResponse {
    success: boolean;
    import_id?: number;
    total_count: number;
    success_count: number;
    message?: string;
}

/**
 * 获取题库列表
 */
export async function listQuestionBank(params?: {
    question_type?: string;
    difficulty?: string;
    is_verified?: boolean;
    limit?: number;
    offset?: number;
}): Promise<QuestionBankListResponse> {
    try {
        const searchParams = new URLSearchParams();
        searchParams.set('user_id', getUserId());
        if (params?.question_type) searchParams.set('question_type', params.question_type);
        if (params?.difficulty) searchParams.set('difficulty', params.difficulty);
        if (params?.is_verified !== undefined) searchParams.set('is_verified', String(params.is_verified));
        if (params?.limit) searchParams.set('limit', String(params.limit));
        if (params?.offset) searchParams.set('offset', String(params.offset));

        const response = await fetch(`${API_BASE_URL}/api/question-bank/items?${searchParams}`, {
            headers: { 'X-User-ID': getUserId() }
        });

        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        return await response.json();
    } catch (error) {
        console.error('获取题库列表失败:', error);
        return { success: false, items: [], total: 0, message: '网络错误' };
    }
}

/**
 * 创建题库条目
 */
export async function createQuestionItem(data: QuestionBankCreateRequest): Promise<{ success: boolean; item_id?: number; message?: string }> {
    try {
        const response = await fetch(`${API_BASE_URL}/api/question-bank/items?user_id=${getUserId()}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-User-ID': getUserId() },
            body: JSON.stringify(data)
        });

        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        return await response.json();
    } catch (error) {
        console.error('创建题库条目失败:', error);
        return { success: false, message: '网络错误' };
    }
}

/**
 * 删除题库条目
 */
export async function deleteQuestionItem(itemId: number): Promise<{ success: boolean; message?: string }> {
    try {
        const response = await fetch(`${API_BASE_URL}/api/question-bank/items/${itemId}?user_id=${getUserId()}`, {
            method: 'DELETE',
            headers: { 'X-User-ID': getUserId() }
        });

        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        return await response.json();
    } catch (error) {
        console.error('删除题库条目失败:', error);
        return { success: false, message: '网络错误' };
    }
}

/**
 * 搜索题库
 */
export async function searchQuestionBank(query: string, limit?: number): Promise<QuestionBankListResponse> {
    try {
        const searchParams = new URLSearchParams();
        searchParams.set('user_id', getUserId());
        searchParams.set('q', query);
        if (limit) searchParams.set('limit', String(limit));

        const response = await fetch(`${API_BASE_URL}/api/question-bank/search?${searchParams}`, {
            headers: { 'X-User-ID': getUserId() }
        });

        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        return await response.json();
    } catch (error) {
        console.error('搜索题库失败:', error);
        return { success: false, items: [], total: 0, message: '网络错误' };
    }
}

/**
 * 批量导入题目
 */
export async function importQuestions(data: QuestionBankImportRequest): Promise<QuestionBankImportResponse> {
    try {
        const response = await fetch(`${API_BASE_URL}/api/question-bank/import?user_id=${getUserId()}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-User-ID': getUserId() },
            body: JSON.stringify(data)
        });

        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        return await response.json();
    } catch (error) {
        console.error('导入题目失败:', error);
        return { success: false, total_count: 0, success_count: 0, message: '网络错误' };
    }
}

/**
 * 从面试会话沉淀题目到题库
 */
export async function saveQuestionFromSession(sessionId: string, questionIndex: number): Promise<{ success: boolean; item_id?: number; message?: string }> {
    try {
        const response = await fetch(
            `${API_BASE_URL}/api/question-bank/save-from-session?session_id=${sessionId}&question_index=${questionIndex}&user_id=${getUserId()}`,
            {
                method: 'POST',
                headers: { 'X-User-ID': getUserId() }
            }
        );

        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        return await response.json();
    } catch (error) {
        console.error('沉淀题目失败:', error);
        return { success: false, message: '网络错误' };
    }
}
