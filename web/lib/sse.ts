export interface SseFrame {
    id?: string;
    event?: string;
    data: string;
}

export function parseSseFrames(buffer: string, chunk: string): { frames: SseFrame[]; buffer: string } {
    const normalized = buffer + chunk.replace(/\r\n/g, '\n');
    const blocks = normalized.split('\n\n');
    const nextBuffer = blocks.pop() || '';
    const frames = blocks
        .map(parseSseBlock)
        .filter((frame): frame is SseFrame => frame !== null);
    return { frames, buffer: nextBuffer };
}

function parseSseBlock(block: string): SseFrame | null {
    const dataLines: string[] = [];
    let id: string | undefined;
    let event: string | undefined;

    for (const line of block.split('\n')) {
        if (line.length === 0 || line.startsWith(':')) continue;
        const separatorIndex = line.indexOf(':');
        const field = separatorIndex >= 0 ? line.slice(0, separatorIndex) : line;
        const rawValue = separatorIndex >= 0 ? line.slice(separatorIndex + 1) : '';
        const value = rawValue.startsWith(' ') ? rawValue.slice(1) : rawValue;

        if (field === 'data') dataLines.push(value);
        if (field === 'id') id = value;
        if (field === 'event') event = value;
    }

    if (dataLines.length === 0) return null;
    return { id, event, data: dataLines.join('\n') };
}
