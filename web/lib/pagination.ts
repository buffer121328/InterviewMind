/** Standard number of records shown on every management-list page. */
export const DEFAULT_PAGE_SIZE = 10;

/** Return at least one page so empty-list controls retain stable numbering. */
export function getTotalPages(total: number, pageSize = DEFAULT_PAGE_SIZE): number {
    return Math.max(1, Math.ceil(Math.max(0, total) / pageSize));
}
