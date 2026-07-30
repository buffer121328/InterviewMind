export type GateThreshold = number | { value: number; comparison?: 'gte' | 'lte' | 'eq' };

export function passesGateThreshold(actual: number, threshold: GateThreshold): boolean {
    const value = typeof threshold === 'number' ? threshold : threshold.value;
    const comparison = typeof threshold === 'number' ? 'gte' : threshold.comparison ?? 'gte';
    if (comparison === 'lte') return actual <= value;
    if (comparison === 'eq') return actual === value;
    return actual >= value;
}
