import type { QuestionBankItem } from './api/questionBank.ts';

type QuestionSource = Pick<QuestionBankItem, 'origin_session_id' | 'source_type'>;
type QuestionAnswer = Pick<QuestionBankItem, 'origin_session_id' | 'source_type' | 'reference_answer'>;

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

/** Interview-origin questions intentionally have no fabricated model answer. */
export function questionReferenceAnswer(item: QuestionAnswer): string {
    if (item.origin_session_id || item.source_type === 'generated' || item.source_type === 'interview') {
        return '暂无';
    }
    return item.reference_answer?.trim() || '暂无';
}
