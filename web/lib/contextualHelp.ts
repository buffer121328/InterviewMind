export interface ContextualHelpAttributes {
    ariaLabel: string;
    tooltipId: string;
}

/** Builds stable accessible attributes shared by compact contextual-help icons. */
export function buildContextualHelpAttributes(label: string, id: string): ContextualHelpAttributes {
    return {
        ariaLabel: `查看${label}`,
        tooltipId: `${id}-tooltip`,
    };
}
