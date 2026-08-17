/** Character threshold for showing the local expand/collapse control. */
export const JOB_DESCRIPTION_PREVIEW_CHARACTER_LIMIT = 420;

export type JobDescriptionBlock =
    | { kind: 'paragraph'; text: string }
    | { kind: 'list'; items: string[] };

const LIST_ITEM_PATTERN = /^(?:[-*•●▪◦]|(?:\d+|[一二三四五六七八九十]+)[、.．])\s*(.+)$/u;

export function shouldOfferJobDescriptionExpansion(value: string): boolean {
    return value.trim().length > JOB_DESCRIPTION_PREVIEW_CHARACTER_LIMIT;
}

/** Splits raw captured JD into ordered paragraphs and common list items without rewriting content. */
export function getJobDescriptionBlocks(value: string): JobDescriptionBlock[] {
    const blocks: JobDescriptionBlock[] = [];
    let paragraphLines: string[] = [];
    let listItems: string[] = [];

    const flushParagraph = () => {
        const text = paragraphLines.join(' ').replace(/\s+/g, ' ').trim();
        if (text) blocks.push({ kind: 'paragraph', text });
        paragraphLines = [];
    };
    const flushList = () => {
        if (listItems.length > 0) blocks.push({ kind: 'list', items: listItems });
        listItems = [];
    };

    for (const rawLine of value.replace(/\r\n?/g, '\n').split('\n')) {
        const line = rawLine.trim();
        if (!line) {
            flushParagraph();
            flushList();
            continue;
        }
        const listItem = line.match(LIST_ITEM_PATTERN)?.[1]?.trim();
        if (listItem) {
            flushParagraph();
            listItems.push(listItem);
            continue;
        }
        flushList();
        paragraphLines.push(line);
    }
    flushParagraph();
    flushList();

    return blocks.length > 0 ? blocks : [{ kind: 'paragraph', text: value.trim() }];
}
