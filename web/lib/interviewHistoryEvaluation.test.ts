import assert from 'node:assert/strict';
import test from 'node:test';

import {
    buildInterviewDatasetConfirmation,
    buildInterviewEvaluationHandoff,
    canConfirmInterviewDataset,
    initializeInterviewReviewCases,
    interviewDraftResult,
    interviewEvaluationErrorMessage,
    interviewEvaluationSourceView,
    parseInterviewQualityRubric,
} from './interviewHistoryEvaluation.ts';

const annotation = {
    case_key: 'case-11',
    category: 'interview_turn',
    expected_facts: ['grounded'],
    forbidden_claims: [],
    quality_rubric: {},
    tags: ['history'],
    severity: 'medium' as const,
    explanation: 'safe',
};

const result = {
    capability: 'interview_turn' as const,
    status: 'needs_review' as const,
    selected_count: 2,
    valid_count: 1,
    failed_count: 1,
    cases: [
        {
            attempt_id: 11,
            session_id: 'session-1',
            source_hash: 'a'.repeat(64),
            question: 'q',
            answer: 'a',
            frozen_input: { messages: [] },
            evidence_refs: ['interview-attempt:11'],
            validation_status: 'valid' as const,
            annotation,
            failure_reason: null,
            model: { model: 'deepseek-v4-flash', fallback_index: 0 },
        },
        {
            attempt_id: 12,
            session_id: 'session-1',
            source_hash: 'b'.repeat(64),
            question: 'q2',
            answer: 'a2',
            frozen_input: {},
            evidence_refs: ['interview-attempt:12'],
            validation_status: 'failed' as const,
            annotation: null,
            failure_reason: 'schema_validation_failed',
            model: {},
        },
    ],
};

test('draft narrowing rejects non-review AgentRun results', () => {
    assert.equal(interviewDraftResult(null), null);
    assert.equal(interviewDraftResult({ result: { status: 'running' } } as never), null);
    assert.equal(interviewDraftResult({ result } as never)?.valid_count, 1);
});

test('review initialization includes only valid cases and never auto-reviews', () => {
    const cases = initializeInterviewReviewCases(result);
    assert.deepEqual(cases.map(item => [item.included, item.reviewed]), [[true, false], [false, false]]);
    assert.equal(canConfirmInterviewDataset(cases), false);
    cases[0].reviewed = true;
    assert.equal(canConfirmInterviewDataset(cases), true);
});

test('confirmation payload excludes frozen input and source text from client authority', () => {
    const cases = initializeInterviewReviewCases(result);
    cases[0].reviewed = true;
    const payload = buildInterviewDatasetConfirmation(' history ', ' v1 ', cases);
    assert.equal(payload.name, 'history');
    assert.equal(payload.version, 'v1');
    const serialized = JSON.stringify(payload);
    assert.equal(serialized.includes('frozen_input'), false);
    assert.equal(serialized.includes('source_hash'), false);
    assert.equal(serialized.includes('question'), false);
    assert.equal(serialized.includes('answer'), false);
});

test('editable quality rubric accepts objects and blocks invalid JSON', () => {
    assert.deepEqual(parseInterviewQualityRubric('{"groundedness":"strict"}'), { groundedness: 'strict' });
    assert.throws(() => parseInterviewQualityRubric('[]'), /JSON 对象/);
    assert.throws(() => parseInterviewQualityRubric('{broken'), SyntaxError);

    const cases = initializeInterviewReviewCases(result);
    cases[0].reviewed = true;
    cases[0].review_error = 'Quality Rubric JSON 格式无效';
    assert.equal(canConfirmInterviewDataset(cases), false);
});

test('source view covers completed, loading, inaccessible, and legacy ineligible states', () => {
    assert.equal(interviewEvaluationSourceView({ completed: false, loading: false, source: null }).state, 'not_completed');
    assert.equal(interviewEvaluationSourceView({ completed: true, loading: true, source: null }).state, 'loading');
    assert.equal(interviewEvaluationSourceView({ completed: true, loading: false, source: null }).state, 'missing');
    const source = {
        session_id: 'session-1', series_id: null, title: 'history', round_index: 1,
        round_type: 'tech_initial', completed_at: '2026-08-13T12:00:00', eligible: false,
        ineligibility_reason: 'missing_persisted_attempt', attempt_count: 0,
        eligible_attempt_count: 0, attempts: [],
    };
    assert.deepEqual(
        interviewEvaluationSourceView({ completed: true, loading: false, source, ineligibilityMessage: '没有持久化逐题回答' }),
        { state: 'ineligible', message: '没有持久化逐题回答' },
    );
    assert.equal(interviewEvaluationSourceView({ completed: true, loading: false, source: { ...source, eligible: true } }).state, 'ready');
});

test('editing and exclusion reset the confirmation gate', () => {
    const cases = initializeInterviewReviewCases(result);
    cases[0].reviewed = true;
    assert.equal(canConfirmInterviewDataset(cases), true);
    cases[0].included = false;
    assert.equal(canConfirmInterviewDataset(cases), false);
    cases[0].included = true;
    cases[0].reviewed = false;
    assert.equal(canConfirmInterviewDataset(cases), false);
});

test('source drift and duplicate confirmation remain actionable and successful handoff focuses the dataset', () => {
    assert.equal(interviewEvaluationErrorMessage(new Error('源问答已发生变化，请重新整理'), 'fallback'), '源问答已发生变化，请重新整理');
    assert.equal(interviewEvaluationErrorMessage(new Error('数据集名称和版本已存在'), 'fallback'), '数据集名称和版本已存在');
    assert.equal(interviewEvaluationErrorMessage(null, '确认创建数据集失败'), '确认创建数据集失败');
    assert.deepEqual(buildInterviewEvaluationHandoff('eds-123'), { view: 'evaluations', datasetId: 'eds-123' });
});
