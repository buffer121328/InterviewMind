import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { experienceImportSummary } from './interviewExperiencePresentation.ts';

describe('experience direct import presentation', () => {
    it('formats governed import counters', () => {
        assert.equal(experienceImportSummary({
            success: true,
            experiences: [],
            questions: [],
            document_count: 2,
            candidate_count: 8,
            filtered_count: 3,
            duplicate_count: 1,
            imported_count: 4,
            failed_count: 0,
        }), '2 篇面经 · 8 道候选 · 模型筛除 3 · 重复 1 · 入库 4');
    });
});
