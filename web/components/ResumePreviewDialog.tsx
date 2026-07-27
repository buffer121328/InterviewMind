import { useState, useRef, useCallback, useEffect } from "react";
import Image from "next/image";

import ReactMarkdown from 'react-markdown';
import rehypeHighlight from 'rehype-highlight';
import 'highlight.js/styles/atom-one-dark.css';
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Copy, FileDown, Check, X, FileText, Edit3, Eye, ImagePlus, Trash2, Save, Printer, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Textarea } from "@/components/ui/textarea";

interface ResumePreviewDialogProps {
    isOpen: boolean;
    onClose: () => void;
    title: string;
    content: string;
    onContentChange?: (newContent: string) => Promise<void>;
}

const A4_HEIGHT_CSS_PIXELS = 1122.52;
// Account for CSS-pixel rounding and the preview border around an exact A4 minimum height.
const A4_MEASUREMENT_TOLERANCE_CSS_PIXELS = 4;

/** Keeps exported resumes self-contained, predictable on A4 paper, and free of editor chrome. */
const RESUME_EXPORT_STYLES = `
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; background: #e9edf2; color: #17202b; }
  body { font-family: "Avenir Next", "Segoe UI", "Microsoft YaHei", sans-serif; font-size: 11pt; line-height: 1.45; }
  .resume-sheet { width: 210mm; min-height: 297mm; margin: 12mm auto; padding: 16mm 17mm; background: #fff; }
  .resume-header { min-height: 34mm; padding-right: 31mm; position: relative; }
  .resume-photo { position: absolute; top: 0; right: 0; width: 25mm; height: 31mm; border: 1px solid #cbd5e1; border-radius: 2mm; object-fit: cover; }
  .resume-placeholder { display: grid; place-items: center; color: #64748b; background: #f8fafc; font-size: 8pt; text-align: center; }
  .resume-content h1 { margin: 0 0 5mm; font-size: 22pt; line-height: 1.1; letter-spacing: -.02em; }
  .resume-content h2 { margin: 6mm 0 2mm; padding-bottom: 1mm; border-bottom: 1px solid #17202b; font-size: 11pt; text-transform: uppercase; letter-spacing: .08em; break-after: avoid; }
  .resume-content h3 { margin: 3mm 0 1mm; font-size: 10.5pt; break-after: avoid; }
  .resume-content p { margin: 0 0 1.5mm; }
  .resume-content blockquote { margin: 0 0 5mm; color: #526173; text-align: center; border: 0; }
  .resume-content ul, .resume-content ol { margin: 1mm 0 2mm; padding-left: 5mm; }
  .resume-content li { margin-bottom: 1mm; }
  .resume-content a { color: inherit; text-decoration: none; }
  .resume-content img { max-width: 100%; }
  h1, h2, h3, p, li, blockquote { orphans: 3; widows: 3; }
  @page { size: A4; margin: 0; }
  @media print {
    html, body { background: #fff; }
    .resume-sheet { margin: 0; box-shadow: none; }
    .resume-content h2, .resume-content h3 { break-before: auto; }
    .resume-content ul, .resume-content ol, .resume-content blockquote { break-inside: avoid; }
  }
`;

/** Mirrors export geometry so page feedback reflects the actual A4 layout rather than a fixed guess. */
const RESUME_PREVIEW_STYLES = `
  .resume-preview-sheet { box-sizing: border-box; width: 210mm; min-height: 297mm; margin: 0 auto 8mm; padding: 16mm 17mm; background: #fff; color: #17202b; font-family: "Avenir Next", "Segoe UI", "Microsoft YaHei", sans-serif; font-size: 11pt; line-height: 1.45; }
  .resume-preview-header { min-height: 36mm; position: relative; }
  .resume-preview-photo { position: absolute; top: 0; right: 0; width: 27mm; height: 33mm; border: 1px solid #cbd5e1; border-radius: 2mm; object-fit: cover; }
  .resume-preview-placeholder { display: grid; place-items: center; color: #64748b; background: #f8fafc; font-size: 8pt; text-align: center; }
  .resume-preview-content h1 { margin: 0 0 5mm; padding-right: 39mm; font-size: 22pt; line-height: 1.1; letter-spacing: -.02em; text-align: center; }
  .resume-preview-content > h1 + p, .resume-preview-content > h1 + blockquote { padding-right: 39mm; }
  .resume-preview-content h2 { margin: 6mm 0 2mm; padding-bottom: 1mm; border-bottom: 1px solid #17202b; font-size: 11pt; text-transform: uppercase; letter-spacing: .08em; }
  .resume-preview-content h3 { margin: 3mm 0 1mm; font-size: 10.5pt; }
  .resume-preview-content p { margin: 0 0 1.5mm; color: #526173; }
  .resume-preview-content blockquote { margin: 0 0 5mm; color: #526173; text-align: center; border: 0; }
  .resume-preview-content ul, .resume-preview-content ol { margin: 1mm 0 2mm; padding-left: 5mm; }
  .resume-preview-content li { margin-bottom: 1mm; color: #526173; }
  .resume-preview-content a { color: inherit; text-decoration: none; }
  .resume-preview-content img { max-width: 100%; }
`;

/** Creates an export document with text nodes for metadata, preventing title injection. */
function createResumeExportDocument(title: string, contentElement: HTMLElement, photo: string | null): Document {
    const exportDocument = document.implementation.createHTMLDocument(title || "简历");
    const style = exportDocument.createElement("style");
    style.textContent = `${RESUME_EXPORT_STYLES}
      .resume-header { min-height: 36mm; padding-right: 0; }
      .resume-photo { width: 27mm; height: 33mm; }
      .resume-content > h1, .resume-content > h1 + p, .resume-content > h1 + blockquote { padding-right: 39mm; }
    `;
    exportDocument.head.appendChild(style);
    const sheet = exportDocument.createElement("main");
    sheet.className = "resume-sheet";
    const header = exportDocument.createElement("header");
    header.className = "resume-header";
    const photoElement = exportDocument.createElement("div");
    photoElement.className = "resume-photo resume-placeholder";
    photoElement.setAttribute("aria-label", photo ? "简历照片" : "照片位置");
    if (photo) {
        const image = exportDocument.createElement("img");
        image.src = photo;
        image.alt = "简历照片";
        image.className = "resume-photo";
        header.appendChild(image);
    } else {
        photoElement.textContent = "PHOTO";
        header.appendChild(photoElement);
    }
    const previewContent = contentElement.querySelector(".resume-preview-content");
    const clonedContent = (previewContent || contentElement).cloneNode(true) as HTMLElement;
    clonedContent.removeAttribute("id");
    clonedContent.querySelectorAll("[data-resume-control]").forEach((control) => control.remove());
    clonedContent.querySelectorAll(".resume-photo-display").forEach((photoNode) => photoNode.remove());
    clonedContent.classList.add("resume-content");
    header.appendChild(clonedContent);
    sheet.appendChild(header);
    exportDocument.body.appendChild(sheet);
    return exportDocument;
}

/** Renders the resume preview dialog UI and coordinates its typed props, local state, and approved backend interactions. */
export function ResumePreviewDialog({
    isOpen,
    onClose,
    title,
    content,
    onContentChange
}: ResumePreviewDialogProps) {
    const [isCopied, setIsCopied] = useState(false);
    const [isEditMode, setIsEditMode] = useState(false);
    const [editableContent, setEditableContent] = useState(content);
    const [savedContent, setSavedContent] = useState(content);
    const [photo, setPhoto] = useState<string | null>(null);
    const [hasChanges, setHasChanges] = useState(false);
    const [isSaving, setIsSaving] = useState(false);
    const [saveError, setSaveError] = useState<string | null>(null);
    const [pageFit, setPageFit] = useState<"one" | "two" | "overflow">("one");
    const fileInputRef = useRef<HTMLInputElement>(null);
    const previewSheetRef = useRef<HTMLDivElement>(null);

    const handleContentChange = useCallback((value: string) => {
        setEditableContent(value);
        setHasChanges(value !== savedContent);
        setSaveError(null);
    }, [savedContent]);

    const handleSave = useCallback(async () => {
        if (!onContentChange) return;
        setIsSaving(true);
        setSaveError(null);
        try {
            await onContentChange(editableContent);
            setSavedContent(editableContent);
            setHasChanges(false);
            toast.success("简历内容已保存");
        } catch (error) {
            const message = error instanceof Error ? error.message : "保存简历失败，请重试";
            setSaveError(message);
            toast.error(message);
        } finally {
            setIsSaving(false);
        }
    }, [editableContent, onContentChange]);

    const updatePageFit = useCallback(() => {
        const sheet = previewSheetRef.current;
        if (!sheet) return;
        const next = sheet.scrollHeight > A4_HEIGHT_CSS_PIXELS * 2 + A4_MEASUREMENT_TOLERANCE_CSS_PIXELS ? "overflow" : sheet.scrollHeight > A4_HEIGHT_CSS_PIXELS + A4_MEASUREMENT_TOLERANCE_CSS_PIXELS ? "two" : "one";
        setPageFit(current => current === next ? current : next);
    }, []);

    useEffect(() => {
        if (isEditMode) return;
        const sheet = previewSheetRef.current;
        if (!sheet) return;
        const frame = requestAnimationFrame(updatePageFit);
        if (typeof ResizeObserver === "undefined") return () => cancelAnimationFrame(frame);
        const observer = new ResizeObserver(updatePageFit);
        observer.observe(sheet);
        return () => { cancelAnimationFrame(frame); observer.disconnect(); };
    }, [editableContent, isEditMode, photo, updatePageFit]);

    /** Handles copy; updates local UI state first and delegates server mutations through the approved API boundary. */
    const handleCopy = async () => {
        try {
            await navigator.clipboard.writeText(editableContent);
            setIsCopied(true);
            toast.success("简历内容已复制");
            setTimeout(() => setIsCopied(false), 2000);
        } catch {
            toast.error("复制失败");
        }
    };

    /** Downloads a standalone, safely constructed HTML file that can be opened or printed later. */
    const handleExportHtml = useCallback(() => {
        const element = document.getElementById('resume-preview-content');
        if (!element) {
            toast.error("无法找到简历内容");
            return;
        }
        const exportDocument = createResumeExportDocument(title, element, photo);
        const blob = new Blob([`<!doctype html>\n${exportDocument.documentElement.outerHTML}`], { type: "text/html;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = `${(title || "resume").replace(/[^\w\u4e00-\u9fff-]+/g, "-")}.html`;
        anchor.click();
        URL.revokeObjectURL(url);
        toast.success("HTML 简历已导出");
    }, [photo, title]);

    /** Opens a sanitized export document and waits for fonts and images before invoking the browser PDF flow. */
    const handlePrint = useCallback(async () => {
        const element = document.getElementById('resume-preview-content');
        if (!element) return toast.error("无法找到简历内容");
        const printWindow = window.open("", "_blank");
        if (!printWindow) return toast.error("无法打开打印窗口，请检查浏览器是否阻止了弹窗");
        // Never truncate content when a third page is unavoidable.
        if (element.scrollHeight > A4_HEIGHT_CSS_PIXELS * 2 + A4_MEASUREMENT_TOLERANCE_CSS_PIXELS) {
            toast.warning("内容超过两页 A4；将完整保留，请在打印预览中确认分页", { duration: 5000 });
        }
        const exportDocument = createResumeExportDocument(title, element, photo);
        printWindow.document.replaceChild(printWindow.document.importNode(exportDocument.documentElement, true), printWindow.document.documentElement);
        await Promise.all(Array.from(printWindow.document.images).map((image) => image.complete ? Promise.resolve() : new Promise<void>((resolve) => { image.addEventListener("load", () => resolve(), { once: true }); image.addEventListener("error", () => resolve(), { once: true }); })));
        await printWindow.document.fonts?.ready;
        printWindow.focus();
        printWindow.print();
        toast.success("打印对话框已打开，请选择“另存为 PDF”保存", { duration: 5000 });
    }, [photo, title]);

    const handlePhotoUpload = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (file) {
            if (!file.type.startsWith('image/')) {
                toast.error("请上传图片文件");
                return;
            }
            if (file.size > 5 * 1024 * 1024) {
                toast.error("图片大小不能超过 5MB");
                return;
            }
            const reader = new FileReader();
            reader.onload = (event) => {
                setPhoto(event.target?.result as string);
                toast.success("照片已添加");
            };
            reader.readAsDataURL(file);
        }
    }, []);

    const handleRemovePhoto = useCallback(() => {
        setPhoto(null);
        if (fileInputRef.current) {
            fileInputRef.current.value = '';
        }
        toast.success("照片已移除");
    }, []);

    const toggleEditMode = useCallback(() => {
        if (isEditMode && hasChanges) {
            // 从编辑模式切换到预览模式时，提示用户保存
            const confirmSwitch = window.confirm("您有未保存的更改，是否放弃更改？");
            if (!confirmSwitch) return;
            setEditableContent(savedContent);
            setHasChanges(false);
        }
        setIsEditMode(!isEditMode);
    }, [isEditMode, hasChanges, savedContent]);

    return (
        <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
            <DialogContent className="max-w-4xl h-[90vh] flex flex-col p-0 gap-0 bg-gray-50/95 backdrop-blur overflow-hidden">
                {/* Header Toolbar */}
                <div className="flex flex-wrap items-center justify-between gap-3 px-4 sm:px-6 py-4 bg-white border-b border-gray-200 shadow-sm z-10">
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 bg-orange-100 rounded-lg flex items-center justify-center">
                            <FileText className="w-6 h-6 text-orange-600" />
                        </div>
                        <div>
                            <DialogTitle className="text-lg font-semibold text-gray-900">{title}</DialogTitle>
                            <p className="text-xs text-gray-500">
                                {isEditMode ? "编辑模式" : "Markdown 预览模式"}
                                {hasChanges && <span className="ml-2 text-amber-500">• 有未保存的更改</span>}
                            </p>
                            {!isEditMode && <p className={cn("mt-0.5 text-xs", pageFit === "overflow" ? "text-amber-700" : "text-gray-500")}>
                                {pageFit === "one" ? "A4 预计 1 页" : pageFit === "two" ? "A4 预计 2 页" : "超过 2 页 A4；导出将保留全部内容"}
                            </p>}
                            {saveError && <p role="alert" className="mt-0.5 text-xs text-red-600">保存失败：{saveError}</p>}
                        </div>
                    </div>

                    <div className="flex flex-wrap items-center justify-end gap-2">
                        {/* 模式切换按钮 */}
                        <Button
                            variant={isEditMode ? "default" : "outline"}
                            size="sm"
                            onClick={toggleEditMode}
                            className={cn("gap-2", isEditMode && "bg-orange-600 hover:bg-orange-700")}
                        >
                            {isEditMode ? <Eye className="w-4 h-4" /> : <Edit3 className="w-4 h-4" />}
                            {isEditMode ? "预览" : "编辑"}
                        </Button>

                        {/* 保存按钮 - 仅在编辑模式且有更改时显示 */}
                        {isEditMode && hasChanges && onContentChange && (
                            <Button
                                variant="default"
                                size="sm"
                                onClick={handleSave}
                                disabled={isSaving}
                                className="gap-2 bg-green-600 hover:bg-green-700"
                            >
                                {isSaving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                                {isSaving ? "保存中..." : "保存"}
                            </Button>
                        )}

                        {/* 照片上传按钮 */}
                        <input
                            type="file"
                            ref={fileInputRef}
                            onChange={handlePhotoUpload}
                            accept="image/*"
                            className="hidden"
                        />
                        <Button
                            variant="outline"
                            size="sm"
                            onClick={() => fileInputRef.current?.click()}
                            className="gap-2"
                        >
                            <ImagePlus className="w-4 h-4" />
                            {photo ? "更换照片" : "添加照片"}
                        </Button>

                        {photo && (
                            <Button
                                variant="outline"
                                size="sm"
                                onClick={handleRemovePhoto}
                                className="gap-2 text-red-600 hover:text-red-700 hover:bg-red-50"
                            >
                                <Trash2 className="w-4 h-4" />
                            </Button>
                        )}

                        <div className="w-px h-6 bg-gray-300 mx-1" />

                        <Button variant="outline" size="sm" onClick={handleCopy} className="gap-2">
                            {isCopied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                            {isCopied ? "已复制" : "复制"}
                        </Button>
                        <Button variant="outline" size="sm" onClick={handleExportHtml} className="gap-2" aria-label="导出简历 HTML">
                            <FileDown className="w-4 h-4" />
                            导出 HTML
                        </Button>
                        <Button variant="default" size="sm" onClick={handlePrint} className="gap-2 bg-slate-900 hover:bg-slate-800" aria-label="打印简历或保存为 PDF">
                            <Printer className="w-4 h-4" />
                            打印 / 保存 PDF
                        </Button>
                        <Button variant="ghost" size="icon" onClick={onClose} className="rounded-full hover:bg-gray-100">
                            <X className="w-5 h-5 text-gray-500" />
                        </Button>
                    </div>
                </div>

                {/* Content Area */}
                <div className="flex-1 overflow-auto bg-gray-100/50 p-6">
                    <style>{RESUME_PREVIEW_STYLES}</style>
                    <div ref={previewSheetRef} id="resume-preview-content" className="resume-preview-sheet shadow-md border border-gray-200 relative">
                        {/* 照片显示区域 */}
                        <div className="resume-preview-photo z-10">
                            {photo ? (
                                <div className="relative group resume-photo-display">
                                    <Image
                                        src={photo}
                                        alt="简历照片"
                                        width={80}
                                        height={96}
                                        unoptimized
                                        className="w-full h-full object-cover rounded-sm"
                                    />
                                    <button
                                        type="button"
                                        data-resume-control
                                        aria-label="移除简历照片"
                                        onClick={handleRemovePhoto}
                                        className="absolute -top-2 -right-2 w-6 h-6 bg-red-500 text-white rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity shadow-md hover:bg-red-600"
                                    >
                                        <X className="w-4 h-4" />
                                    </button>
                                </div>
                            ) : (
                                <div className="resume-preview-placeholder resume-photo-display w-full h-full border border-dashed border-slate-300 rounded-sm tracking-widest" aria-label="照片位置">
                                    PHOTO
                                </div>
                            )}
                        </div>

                        <div className="resume-preview-header">
                        {isEditMode ? (
                            /* 编辑模式 */
                            <div className="min-h-[900px]">
                                <Textarea
                                    value={editableContent}
                                    onChange={(e) => handleContentChange(e.target.value)}
                                    className="w-full min-h-[900px] font-mono text-sm border-gray-300 focus:border-orange-500 focus:ring-orange-500 resize-none"
                                    placeholder="在此编辑您的简历内容（支持 Markdown 格式）..."
                                />
                                <div className="mt-4 p-4 bg-gray-50 rounded-lg border border-gray-200">
                                    <h4 className="text-sm font-medium text-gray-700 mb-2">Markdown 格式提示</h4>
                                    <div className="grid grid-cols-2 gap-2 text-xs text-gray-600">
                                        <div><code className="bg-gray-200 px-1 rounded"># 标题</code> - 一级标题</div>
                                        <div><code className="bg-gray-200 px-1 rounded">## 标题</code> - 二级标题</div>
                                        <div><code className="bg-gray-200 px-1 rounded">**粗体**</code> - 粗体文本</div>
                                        <div><code className="bg-gray-200 px-1 rounded">*斜体*</code> - 斜体文本</div>
                                        <div><code className="bg-gray-200 px-1 rounded">- 项目</code> - 无序列表</div>
                                        <div><code className="bg-gray-200 px-1 rounded">1. 项目</code> - 有序列表</div>
                                    </div>
                                </div>
                            </div>
                        ) : (
                            /* 预览模式 */
                            <div className="resume-preview-content">
                                <ReactMarkdown
                                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                                    rehypePlugins={[rehypeHighlight as any]}
                                >
                                    {editableContent}
                                </ReactMarkdown>
                            </div>
                        )}
                        </div>
                    </div>
                </div>
            </DialogContent>
        </Dialog>
    );
}
