/** Canonical A4 resume styles shared by the live preview and standalone exports. */
export const RESUME_SHEET_STYLES = `
  .resume-preview-sheet {
    --resume-ink: #172033;
    --resume-muted: #526173;
    --resume-teal: #0f766e;
    --resume-teal-dark: #164e63;
    --resume-soft: #ecfdf5;
    position: relative;
    box-sizing: border-box;
    width: 210mm;
    min-height: 297mm;
    margin: 0 auto 8mm;
    padding: 17mm 17mm 16mm;
    overflow: visible;
    border: 1px solid #e2e8f0;
    background: #fff;
    color: var(--resume-ink);
    box-shadow: 0 14px 42px rgba(15, 23, 42, .14);
    font-family: "Avenir Next", "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif;
    font-size: 11pt;
    line-height: 1.5;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }
  .resume-preview-sheet::before {
    content: "";
    position: absolute;
    inset: 0 0 auto;
    height: 7mm;
    background: linear-gradient(90deg, var(--resume-teal-dark), var(--resume-teal), #14b8a6);
  }
  .resume-preview-header { min-height: 36mm; position: relative; }
  .resume-preview-photo {
    position: absolute;
    z-index: 10;
    top: 2mm;
    right: 0;
    width: 27mm;
    height: 33mm;
    overflow: hidden;
    border: 2px solid #ccfbf1;
    border-radius: 2mm;
    background: #f8fafc;
    box-shadow: 0 4px 12px rgba(15, 118, 110, .14);
  }
  .resume-preview-photo > div,
  .resume-preview-photo img { width: 100%; height: 100%; object-fit: cover; }
  .resume-preview-placeholder {
    display: grid;
    place-items: center;
    color: #64748b;
    background: #f8fafc;
    font-size: 8pt;
    text-align: center;
  }
  .resume-preview-content h1 {
    margin: 4mm 0 2mm;
    padding-right: 39mm;
    color: var(--resume-teal-dark);
    font-size: 25pt;
    line-height: 1.08;
    letter-spacing: -.03em;
    text-align: center;
  }
  .resume-preview-content > h1 + p,
  .resume-preview-content > h1 + blockquote { padding-right: 39mm; text-align: center; }
  .resume-preview-content h2 {
    margin: 6mm 0 2.5mm;
    padding: 1.8mm 3mm;
    border-radius: 1.6mm;
    background: linear-gradient(90deg, var(--resume-teal-dark), var(--resume-teal));
    color: #fff;
    font-size: 11.5pt;
    line-height: 1.2;
    letter-spacing: .08em;
    break-after: avoid-page;
    page-break-after: avoid;
  }
  .resume-preview-content h3 {
    margin: 3.5mm 0 1mm;
    padding-left: 2.5mm;
    border-left: 1.2mm solid #14b8a6;
    color: var(--resume-ink);
    font-size: 11pt;
    break-after: avoid-page;
    page-break-after: avoid;
  }
  .resume-preview-content p { margin: 0 0 1.8mm; color: var(--resume-muted); }
  .resume-preview-content blockquote { margin: 0 0 5mm; border: 0; color: var(--resume-muted); text-align: center; }
  .resume-preview-content ul,
  .resume-preview-content ol { margin: 1mm 0 2.5mm; padding-left: 5.5mm; }
  .resume-preview-content li { margin-bottom: 1.2mm; color: #334155; break-inside: avoid-page; }
  .resume-preview-content strong { color: var(--resume-ink); }
  .resume-preview-content code { padding: .2mm 1mm; border-radius: 1mm; background: var(--resume-soft); color: var(--resume-teal-dark); }
  .resume-preview-content a { color: var(--resume-teal); text-decoration: none; overflow-wrap: anywhere; }
  .resume-preview-content img { max-width: 100%; }
  .resume-preview-content h1,
  .resume-preview-content h2,
  .resume-preview-content h3,
  .resume-preview-content p,
  .resume-preview-content li,
  .resume-preview-content blockquote { orphans: 3; widows: 3; }
`;

/** Standalone document chrome and print rules wrapped around the canonical preview sheet. */
export const RESUME_STANDALONE_STYLES = `
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; background: #e8eef1; color: #172033; }
  body { min-width: 210mm; padding: 12mm 0; }
  ${RESUME_SHEET_STYLES}
  @page { size: A4; margin: 0; }
  @media print {
    html, body { width: 100%; min-width: 0; margin: 0; padding: 0; background: #fff; }
    .resume-preview-sheet { width: 100%; min-height: 0; margin: 0; padding-bottom: 8mm; border: 0; box-shadow: none; }
    .resume-preview-content ul,
    .resume-preview-content ol,
    .resume-preview-content blockquote { break-inside: avoid-page; }
  }
`;

/** Escapes document metadata without altering the already-sanitized React-rendered resume markup. */
function escapeHtml(value: string): string {
    return value
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
}

/** Builds a self-contained HTML file around the exact cloned preview sheet. */
export function buildStandaloneResumeHtml(title: string, sheetHtml: string): string {
    return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escapeHtml(title || '简历')}</title><style>${RESUME_STANDALONE_STYLES}</style></head><body>${sheetHtml}</body></html>`;
}
