'use client';

import { ChevronLeft, ChevronRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { DEFAULT_PAGE_SIZE, getTotalPages } from '@/lib/pagination';
import { cn } from '@/lib/utils';

interface PaginationControlsProps {
    page: number;
    total: number;
    onPageChange: (page: number) => void;
    pageSize?: number;
    loading?: boolean;
    className?: string;
}

/** Renders the shared ten-record list pager without owning server or filter state. */
export function PaginationControls({
    page,
    total,
    onPageChange,
    pageSize = DEFAULT_PAGE_SIZE,
    loading = false,
    className,
}: PaginationControlsProps) {
    const totalPages = getTotalPages(total, pageSize);
    const start = total === 0 ? 0 : (page - 1) * pageSize + 1;
    const end = Math.min(total, page * pageSize);

    return (
        <nav
            aria-label="列表分页"
            className={cn('flex flex-wrap items-center justify-between gap-3 text-sm text-slate-500', className)}
        >
            <span>共 {total} 条 · 当前 {start}-{end} 条</span>
            <div className="flex items-center gap-2">
                <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={loading || page <= 1}
                    onClick={() => onPageChange(page - 1)}
                    aria-label="上一页"
                >
                    <ChevronLeft className="h-4 w-4" />
                    上一页
                </Button>
                <span className="min-w-20 text-center">第 {page} / {totalPages} 页</span>
                <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={loading || page >= totalPages}
                    onClick={() => onPageChange(page + 1)}
                    aria-label="下一页"
                >
                    下一页
                    <ChevronRight className="h-4 w-4" />
                </Button>
            </div>
        </nav>
    );
}
