'use client';

import { Info } from 'lucide-react';

import { buildContextualHelpAttributes } from '@/lib/contextualHelp';
import { cn } from '@/lib/utils';

interface ContextualHelpIconProps {
    id: string;
    label: string;
    children: React.ReactNode;
    className?: string;
}

/** Shows low-frequency help on pointer hover or keyboard focus without occupying the default layout. */
export function ContextualHelpIcon({ id, label, children, className }: ContextualHelpIconProps) {
    const attributes = buildContextualHelpAttributes(label, id);
    return (
        <span className={cn('group/help relative inline-flex', className)}>
            <button
                type="button"
                aria-label={attributes.ariaLabel}
                aria-describedby={attributes.tooltipId}
                className="inline-flex h-8 items-center gap-1.5 rounded-full border border-slate-200 bg-white px-2.5 text-xs font-medium text-slate-600 shadow-sm transition hover:border-teal-300 hover:text-teal-700 focus:outline-none focus:ring-2 focus:ring-teal-200"
            >
                <Info className="h-3.5 w-3.5" />
                {label}
            </button>
            <span
                id={attributes.tooltipId}
                role="tooltip"
                className="pointer-events-none absolute right-0 top-full z-30 mt-2 w-72 rounded-xl bg-slate-900 px-3 py-2.5 text-left text-xs font-normal leading-5 text-white opacity-0 shadow-xl transition-opacity group-hover/help:opacity-100 group-focus-within/help:opacity-100"
            >
                {children}
            </span>
        </span>
    );
}
