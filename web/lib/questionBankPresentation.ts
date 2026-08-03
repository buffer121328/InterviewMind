import type { QuestionBankFollowup, QuestionBankItem } from './api/questionBank.ts';

type QuestionSource = Pick<QuestionBankItem, 'origin_session_id' | 'source_type'>;

/** Converts persisted source codes into user-facing provenance labels. */
export function questionSourceLabel(item: QuestionSource): string {
    if (item.origin_session_id) return '模拟面试';
    const labels: Record<string, string> = {
        manual: '手动添加',
        generated: '模拟面试',
        interview: '模拟面试',
        experience: '面经采集',
        upload: '文件导入',
        imported: '文件导入',
    };
    return labels[item.source_type] || item.source_type || '未知来源';
}

/** Keeps main-question answer points empty until the product-level point model is defined. */
export function questionAnswerPoints(item: Pick<QuestionBankItem, 'reference_answer'>): string[] {
    void item;
    return [];
}

/** Keeps follow-up answer points empty while preserving the shared card empty state. */
export function questionFollowupAnswerPoints(item: Pick<QuestionBankFollowup, 'reference_answer'>): string[] {
    void item;
    return [];
}
