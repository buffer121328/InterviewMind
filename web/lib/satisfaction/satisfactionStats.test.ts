import assert from 'node:assert/strict';
import test from 'node:test';
import { formatSatisfactionStats, TOP_ASPECT_LIMIT } from './satisfactionStats.ts';
import type { SatisfactionStats } from '../api/satisfaction.ts';

/** 构造最小可用的统计数据 fixture */
function fixture(overrides: Partial<SatisfactionStats> = {}): SatisfactionStats {
    return {
        total_count: 0,
        rating_count: 0,
        avg_rating: null,
        rating_distribution: { '1': 0, '2': 0, '3': 0, '4': 0, '5': 0 },
        satisfied_frequencies: [],
        dissatisfied_frequencies: [],
        ...overrides,
    };
}

test('空数据返回 null，用于空态判断', () => {
    assert.equal(formatSatisfactionStats(null), null);
    assert.equal(formatSatisfactionStats(fixture()), null);
    assert.equal(formatSatisfactionStats(fixture({ total_count: 0, avg_rating: 3 })), null);
});

test('avg_rating 为 null 时展示占位文案', () => {
    const view = formatSatisfactionStats(fixture({
        total_count: 3,
        rating_count: 0,
        avg_rating: null,
        satisfied_frequencies: [{ aspect: '问题质量', count: 2 }],
    }));
    assert.ok(view);
    assert.equal(view.totalCount, 3);
    assert.equal(view.avgRating, '暂无');
});

test('平均星级保留 1 位小数', () => {
    const view = formatSatisfactionStats(fixture({
        total_count: 5,
        rating_count: 4,
        avg_rating: 4.25,
    }));
    assert.ok(view);
    assert.equal(view.avgRating, '4.3');
});

test('星级分布计数与比例正确', () => {
    const view = formatSatisfactionStats(fixture({
        total_count: 5,
        rating_count: 4,
        avg_rating: 4,
        rating_distribution: { '1': 1, '2': 0, '3': 1, '4': 1, '5': 1 },
    }));
    assert.ok(view);
    assert.equal(view.ratingCount, 4);
    assert.equal(view.distribution.length, 5);
    assert.equal(view.distribution[0].star, 1);
    assert.equal(view.distribution[0].count, 1);
    assert.equal(view.distribution[0].ratio, 0.25);
    assert.equal(view.distribution[2].count, 1);
    assert.equal(view.distribution[2].ratio, 0.25);
    assert.equal(view.distribution[4].count, 1);
});

test('星级比例分母回退到分布计数之和', () => {
    // rating_count 为 0 但分布有数据时，仍按分布之和计算比例
    const view = formatSatisfactionStats(fixture({
        total_count: 10,
        rating_count: 0,
        avg_rating: 3.5,
        rating_distribution: { '1': 0, '2': 0, '3': 0, '4': 1, '5': 1 },
    }));
    assert.ok(view);
    assert.equal(view.distribution[3].ratio, 0.5);
    assert.equal(view.distribution[4].ratio, 0.5);
});

test('满意/不满意方面按 Top 截断', () => {
    const freq = Array.from({ length: 12 }, (_, index) => ({ aspect: `aspect-${index}`, count: 12 - index }));
    const view = formatSatisfactionStats(fixture({
        total_count: 10,
        rating_count: 5,
        avg_rating: 3,
        rating_distribution: { '1': 1, '2': 1, '3': 1, '4': 1, '5': 1 },
        satisfied_frequencies: freq,
        dissatisfied_frequencies: freq.slice(0, 3),
    }));
    assert.ok(view);
    assert.equal(view.satisfiedTop.length, TOP_ASPECT_LIMIT);
    assert.equal(view.satisfiedTop.length, 8);
    assert.equal(view.satisfiedTop[0].aspect, 'aspect-0');
    assert.equal(view.satisfiedTop[0].count, 12);
    assert.equal(view.dissatisfiedTop.length, 3);
});
