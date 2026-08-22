const STORAGE_KEY = 'evaluation-regression-acknowledged-v1';
const MAX_ACKNOWLEDGEMENTS = 500;

type StorageLike = Pick<Storage, 'getItem' | 'setItem'>;

/** Reads bounded regression acknowledgement IDs without allowing malformed storage to break the overview. */
export function loadAcknowledgedRegressionIds(storage: StorageLike | null | undefined): Set<string> {
    if (!storage) return new Set();
    try {
        const parsed: unknown = JSON.parse(storage.getItem(STORAGE_KEY) ?? '[]');
        if (!Array.isArray(parsed)) return new Set();
        return new Set(
            parsed
                .filter((value): value is string => typeof value === 'string' && value.length > 0 && value.length <= 200)
                .slice(-MAX_ACKNOWLEDGEMENTS),
        );
    } catch {
        return new Set();
    }
}

/** Persists only bounded run IDs; storage failures are non-fatal to evaluation browsing. */
export function saveAcknowledgedRegressionIds(
    ids: Iterable<string>,
    storage: StorageLike | null | undefined,
): void {
    if (!storage) return;
    try {
        storage.setItem(STORAGE_KEY, JSON.stringify([...new Set(ids)].slice(-MAX_ACKNOWLEDGEMENTS)));
    } catch {
        // Private browsing and quota failures must not block the acknowledgement action.
    }
}

