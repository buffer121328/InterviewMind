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

/** Splits stored prose or list-shaped answer text into lossless, scan-friendly review points. */
function answerPoints(value?: string): string[] {
    const content = value?.trim();
    if (!content) return [];

    return content
        .split(/\r?\n+/)
        .flatMap((line) => {
            const cleaned = line
                .trim()
                .replace(/^#{1,6}\s*/, '')
                .replace(/^(?:[-*•]+|\d+[.)、]|[（(]?\d+[）)])\s*/, '')
                .trim();
            if (!cleaned) return [];
            return cleaned.match(/[^。！？；;]+[。！？；;]?/g) ?? [cleaned];
        })
        .map((point) => point.trim())
        .filter(Boolean);
}

/** Returns persisted main-question answer content as scan-friendly review points regardless of source. */
export function questionAnswerPoints(item: QuestionAnswer): string[] {
    return answerPoints(item.reference_answer);
}
