/**
 * 满意度统计展示纯函数
 * 把后端返回的 SatisfactionStats 整理为可直接渲染的结构。
 */

import type { SatisfactionStats } from '../api/satisfaction';

/** 满意/不满意方面 Top 展示的最大条数 */
export const TOP_ASPECT_LIMIT = 8;

/** 星级分布单行（star 为 1-5 星） */
export interface SatisfactionDistributionRow {
    star: 1 | 2 | 3 | 4 | 5;
    count: number;
    /** 该星级占已评分提交的比例，范围 0-1 */
    ratio: number;
}

/** 单条方面的频次展示 */
export interface SatisfactionFrequencyRow {
    aspect: string;
    count: number;
}

/** 整理后的满意度统计展示结构 */
export interface SatisfactionStatsView {
    totalCount: number;
    ratingCount: number;
    /** 平均星级（保留 1 位小数）；无评分时为占位文案 */
    avgRating: string;
    distribution: SatisfactionDistributionRow[];
    satisfiedTop: SatisfactionFrequencyRow[];
    dissatisfiedTop: SatisfactionFrequencyRow[];
}

/**
 * 把后端满意度统计整理为展示结构。
 * 无数据（stats 为 null 或 total_count === 0）时返回 null，用于空态判断。
 * @param stats 后端返回的满意度统计
 */
export function formatSatisfactionStats(stats: SatisfactionStats | null): SatisfactionStatsView | null {
    if (!stats || stats.total_count <= 0) return null;

    // 星级比例的分母：优先用已评分数量，兜底用分布计数之和
    const ratedTotal = stats.rating_count > 0
        ? stats.rating_count
        : Object.values(stats.rating_distribution).reduce((sum, count) => sum + count, 0);
    const denominator = Math.max(ratedTotal, 1);

    const distribution = (['1', '2', '3', '4', '5'] as const).map(star => {
        const count = stats.rating_distribution[star] ?? 0;
        return { star: Number(star) as 1 | 2 | 3 | 4 | 5, count, ratio: count / denominator };
    });

    return {
        totalCount: stats.total_count,
        ratingCount: stats.rating_count,
        avgRating: stats.avg_rating == null || !Number.isFinite(stats.avg_rating)
            ? '暂无'
            : stats.avg_rating.toFixed(1),
        distribution,
        satisfiedTop: stats.satisfied_frequencies.slice(0, TOP_ASPECT_LIMIT),
        dissatisfiedTop: stats.dissatisfied_frequencies.slice(0, TOP_ASPECT_LIMIT),
    };
}
