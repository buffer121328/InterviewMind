import type { LinkedResumeAsset } from '@/lib/api/applications';

/** Builds a safe Markdown filename and content for an already owner-scoped asset. */
export function buildResumeMarkdownDownload(asset: LinkedResumeAsset): { filename: string; content: string } {
    const stem = asset.title.trim().replace(/[\\/:*?"<>|]+/g, '-').replace(/\s+/g, '-').replace(/-+/g, '-').replace(/^-|-$/g, '').slice(0, 80) || `resume-${asset.id}`;
    return { filename: `${stem}.md`, content: asset.content };
}

/** Downloads persisted Markdown without creating a model or server-side export task. */
export function downloadResumeMarkdown(asset: LinkedResumeAsset): void {
    const download = buildResumeMarkdownDownload(asset);
    const url = URL.createObjectURL(new Blob([download.content], { type: 'text/markdown;charset=utf-8' }));
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = download.filename;
    anchor.click();
    URL.revokeObjectURL(url);
}
