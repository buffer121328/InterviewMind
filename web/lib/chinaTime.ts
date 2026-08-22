/** Shared China Standard Time presentation boundary for every user-visible timestamp. */
export const CHINA_TIME_ZONE = 'Asia/Shanghai';

/** Parses explicit-offset timestamps and legacy backend UTC-naive values consistently. */
export function parsePersistedTimestamp(value?: string | null): Date | null {
    if (!value) return null;
    const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`;
    const date = new Date(normalized);
    return Number.isNaN(date.getTime()) ? null : date;
}

/** Renders a persisted timestamp in China Standard Time without relying on the browser timezone. */
export function formatChinaDateTime(
    value?: string | null,
    options: Intl.DateTimeFormatOptions = {},
): string {
    const date = parsePersistedTimestamp(value);
    if (!date) return value || '-';
    return date.toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: options.second,
        hour12: false,
        timeZone: CHINA_TIME_ZONE,
        ...options,
    });
}

/** Renders a persisted time-of-day in China Standard Time. */
export function formatChinaTime(value?: string | null): string {
    const date = parsePersistedTimestamp(value);
    return date ? date.toLocaleTimeString('zh-CN', {
        hour: '2-digit', minute: '2-digit', hour12: false, timeZone: CHINA_TIME_ZONE,
    }) : value || '-';
}
