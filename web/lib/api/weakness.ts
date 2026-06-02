/**
 * 短板地图 API 接口
 */

import { API_BASE_URL, getUserId } from './config';

// 短板分类
export interface WeaknessCategory {
    category: string;
    description: string;
    severity: 'high' | 'medium' | 'low';
}

// 问题失败分析
export interface QuestionFailure {
    question: string;
    user_answer: string;
    issue: string;
    better_example: string;
}

// 改进行动项
export interface ImprovementAction {
    action: string;
    priority: number;
    estimated_effort: string;
}

// 短板报告数据
export interface WeaknessReportData {
    weakness_categories: WeaknessCategory[];
    question_failures: QuestionFailure[];
    improvement_actions: ImprovementAction[];
    recommended_questions: string[];
    priority_order: string[];
}

// 短板报告完整项
export interface WeaknessReport {
    id: number;
    user_id: string;
    session_id: string;
    series_id: string | null;
    report_data: WeaknessReportData;
    created_at: string;
    updated_at: string;
}

// API 响应
export interface WeaknessResponse {
    success: boolean;
    report?: WeaknessReport;
    message?: string;
}

export interface WeaknessHistoryResponse {
    success: boolean;
    reports?: WeaknessReport[];
    message?: string;
}

/**
 * 生成短板地图报告
 */
export async function generateWeaknessReport(
    sessionId: string,
    apiConfig?: any
): Promise<WeaknessResponse> {
    try {
        const response = await fetch(`${API_BASE_URL}/api/chat/weakness/generate`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-User-ID': getUserId()
            },
            body: JSON.stringify({
                session_id: sessionId,
                api_config: apiConfig
            })
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        return data;
    } catch (error) {
        console.error('生成短板地图失败:', error);
        return {
            success: false,
            message: '网络错误，请稍后重试'
        };
    }
}

/**
 * 获取指定会话的短板地图
 */
export async function getSessionWeaknessReport(
    sessionId: string
): Promise<WeaknessResponse> {
    try {
        const response = await fetch(`${API_BASE_URL}/api/chat/weakness/session/${sessionId}`, {
            headers: { 'X-User-ID': getUserId() }
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        return data;
    } catch (error) {
        console.error('获取短板地图失败:', error);
        return {
            success: false,
            message: '网络错误，请稍后重试'
        };
    }
}

/**
 * 获取短板地图历史列表
 */
export async function getWeaknessHistory(): Promise<WeaknessHistoryResponse> {
    try {
        const response = await fetch(`${API_BASE_URL}/api/chat/weakness/history`, {
            headers: { 'X-User-ID': getUserId() }
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        return data;
    } catch (error) {
        console.error('获取短板地图历史失败:', error);
        return {
            success: false,
            message: '网络错误，请稍后重试'
        };
    }
}
