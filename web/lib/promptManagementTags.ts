export const promptManagementTagCategories = ['业务领域', '工作职责', '处理阶段'] as const;
export type PromptManagementTagCategory = (typeof promptManagementTagCategories)[number];

/** Structured functional metadata owned by the backend Prompt registry. */
export interface PromptManagementTag {
    key: string;
    label: string;
    category: PromptManagementTagCategory;
}

/** Returns options for one independent prompt-management filter. */
export function getPromptManagementTagsForCategory(
    tags: PromptManagementTag[] | undefined,
    category: PromptManagementTagCategory,
): PromptManagementTag[] {
    return (tags ?? []).filter(tag => tag.category === category);
}

/** Returns backend-owned tags while hiding a duplicated legacy functional-group badge. */
export function getVisiblePromptManagementTags(
    managementTags: PromptManagementTag[] | undefined,
    functionalGroup: string,
): PromptManagementTag[] {
    const seen = new Set<string>();
    return (managementTags ?? []).filter(tag => {
        if (tag.label === functionalGroup || seen.has(tag.key)) return false;
        seen.add(tag.key);
        return true;
    });
}
