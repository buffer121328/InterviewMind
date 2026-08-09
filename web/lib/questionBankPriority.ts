import type {
    QuestionBankCreateRequest,
    QuestionBankItem,
    QuestionPriority,
} from './api/questionBank';

const PRIORITY_LABELS: Record<QuestionPriority, string> = {
    required: '必选',
    high: '高',
    low: '低',
};

/** Returns the stable Chinese label for a persisted question-bank priority. */
export function priorityLabel(priority: QuestionPriority): string {
    return PRIORITY_LABELS[priority];
}

/** Creates a clean form for a new low-priority question. */
export function defaultQuestionBankForm(): QuestionBankCreateRequest {
    return {
        question_text: '',
        reference_answer: '',
        tags: [],
        difficulty: 'medium',
        target_skill: '',
        question_type: 'tech',
        priority: 'low',
    };
}

/** Converts one owner-visible item to the complete editable API payload. */
export function toQuestionBankForm(item: QuestionBankItem): QuestionBankCreateRequest {
    return {
        question_text: item.question_text,
        reference_answer: item.reference_answer ?? '',
        tags: item.tags,
        difficulty: item.difficulty,
        target_skill: item.target_skill ?? '',
        question_type: item.question_type,
        priority: item.priority,
        source_type: item.source_type,
    };
}
