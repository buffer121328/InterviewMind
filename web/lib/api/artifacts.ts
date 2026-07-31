import { buildApiUrl, getUserId } from './config';

/** Supported persisted report sources that can be privately exported by the backend. */
export type ArtifactSourceType = 'generated_resume' | 'agent_run' | 'resume_result' | 'jd_analysis' | 'weakness_report' | 'interview_report';
/** Formats rendered on the server and stored in the private Docker volume. */
export type ArtifactFormat = 'html' | 'pdf';

/** Safe export metadata returned without revealing a volume path or object storage key. */
export interface Artifact {
    id: number;
    source_type: ArtifactSourceType;
    source_id: string;
    title: string;
    format: ArtifactFormat;
    mime_type: string;
    size_bytes: number;
    created_at: string;
    download_url: string;
}

/** Creates or reuses a server-side private report export after backend owner validation. */
export async function exportArtifact(sourceType: ArtifactSourceType, sourceId: string | number, format: ArtifactFormat): Promise<Artifact> {
    const response = await fetch(buildApiUrl('/api/artifacts/export'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-User-ID': getUserId() },
        body: JSON.stringify({ source_type: sourceType, source_id: String(sourceId), format }),
    });
    if (!response.ok) {
        const payload = await response.json().catch(() => null) as { detail?: string } | null;
        throw new Error(payload?.detail || '生成下载文件失败');
    }
    return response.json() as Promise<Artifact>;
}

/** Downloads via the authenticated API boundary before triggering a browser-only Blob save. */
export async function downloadArtifact(artifact: Artifact): Promise<void> {
    const response = await fetch(buildApiUrl(artifact.download_url), { headers: { 'X-User-ID': getUserId() } });
    if (!response.ok) throw new Error('下载文件失败或无权访问');
    const contentDisposition = response.headers.get('content-disposition') || '';
    const filename = contentDisposition.match(/filename="?([^";]+)"?/)?.[1] || `${artifact.title}.${artifact.format}`;
    const objectUrl = URL.createObjectURL(await response.blob());
    const anchor = document.createElement('a');
    anchor.href = objectUrl;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(objectUrl);
}
