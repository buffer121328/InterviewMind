/** Builds the resume-workspace history title from local date/time and a stable task label. */
export function formatResumeWorkspaceTitle(createdAt: string): string {
    const date = new Date(createdAt);
    if (Number.isNaN(date.getTime())) return '简历优化';
    const parts = new Intl.DateTimeFormat('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
    }).formatToParts(date);
    const value = (type: Intl.DateTimeFormatPartTypes) => parts.find(part => part.type === type)?.value || '';
    return `${value('year')}-${value('month')}-${value('day')} ${value('hour')}:${value('minute')} —— 简历优化`;
}
