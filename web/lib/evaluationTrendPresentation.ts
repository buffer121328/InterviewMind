import { formatChinaDateTime } from './chinaTime.ts';
import type { EvaluationTrendPoint } from '@/lib/api/evaluations';

export type TrendLatencyUnit = '秒' | '分钟';

interface QualityTrendDatum {
    name: string;
    success: number | null;
    sample: number;
}

interface LatencyTrendDatum {
    name: string;
    latency: number | null;
    sample: number;
}

export interface EvaluationTrendPresentation {
    latencyUnit: TrendLatencyUnit;
    qualityData: QualityTrendDatum[];
    latencyData: LatencyTrendDatum[];
    hasQualityData: boolean;
    hasLatencyData: boolean;
}

/** Chooses one shared latency unit so points in a chart remain directly comparable. */
export function selectTrendLatencyUnit(points: Pick<EvaluationTrendPoint, 'p95_latency_ms'>[]): TrendLatencyUnit {
    const maximum = Math.max(0, ...points.map((point) => point.p95_latency_ms ?? 0));
    return maximum >= 60_000 ? '分钟' : '秒';
}

/** Formats a chart percentage value while keeping unavailable data visibly unavailable. */
export function formatTrendPercentage(value: number | null | undefined): string {
    return value == null || !Number.isFinite(value) ? '-' : `${formatDisplayNumber(value)}%`;
}

/** Formats raw millisecond latency in the chart's shared human-readable unit. */
export function formatTrendLatency(value: number | null | undefined, unit: TrendLatencyUnit): string {
    if (value == null || !Number.isFinite(value)) return '-';
    const displayedValue = unit === '分钟' ? value / 60_000 : value / 1_000;
    return `${formatDisplayNumber(displayedValue)} ${unit}`;
}

/** Builds independent quality and latency series from API trend points without changing raw API data. */
export function buildEvaluationTrendPresentation(points: EvaluationTrendPoint[]): EvaluationTrendPresentation {
    const latencyUnit = selectTrendLatencyUnit(points);
    const qualityData = points.map((point) => ({
        name: formatTrendTimestamp(point.created_at),
        success: toPercentage(point.complete_success_rate),
        sample: point.sample_count,
    }));
    const latencyData = points.map((point) => ({
        name: formatTrendTimestamp(point.created_at),
        latency: point.p95_latency_ms,
        sample: point.sample_count,
    }));

    return {
        latencyUnit,
        qualityData,
        latencyData,
        hasQualityData: qualityData.some((point) => point.success != null),
        hasLatencyData: latencyData.some((point) => point.latency != null),
    };
}

function toPercentage(value: number | null): number | null {
    return value == null || !Number.isFinite(value) ? null : value * 100;
}

function formatTrendTimestamp(value: string): string {
    return formatChinaDateTime(value, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', year: undefined });
}

function formatDisplayNumber(value: number): string {
    return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: value < 10 ? 1 : 0 }).format(value);
}
