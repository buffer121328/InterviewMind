import { useState, useEffect } from 'react';
import Image from 'next/image';
import { motion, AnimatePresence } from 'framer-motion';
import { PanelLeftClose, Plus, Settings, User, Bot, FileText, MessageCircle, Target, Trash2, MoreHorizontal, Briefcase, BookOpen } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { SessionList } from './SessionList';
import { ResumeHistoryList } from './ResumeHistoryList';
import { GeneratedResumeList } from './GeneratedResumeList';
import { ResumePreviewDialog } from './ResumePreviewDialog';
import { cn } from '@/lib/utils';
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { useInterviewStore } from '@/store/useInterviewStore';
import { updateGeneratedResume } from '@/lib/api/resume';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from "@/components/ui/alert-dialog";

interface SessionSidebarProps {
    isOpen: boolean;
    onClose: () => void;
    onOpenSettings: () => void;
    currentView: 'interview' | 'resume' | 'applications' | 'questionbank' | 'boss';
    onViewChange: (view: 'interview' | 'resume' | 'applications' | 'questionbank' | 'boss') => void;
}

export function SessionSidebar({
    isOpen,
    onClose,
    onOpenSettings,
    currentView,
    onViewChange
}: SessionSidebarProps) {
    const {
        // Interview Sessions
        sessions,
        currentSession,
        sessionLoading,
        selectSession,
        createNewSession,
        deleteSession,
        updateSessionTitle,
        togglePinSession,

        // Resume History
        resumeResults,
        currentResumeResult,
        resumeResultLoading,
        fetchResumeResults,
        selectResumeResult,
        deleteResumeResult,
        clearResumeResult,

        // Generated Resumes
        generatedResumes,
        generatedResumesLoading,
        fetchGeneratedResumes,
        selectGeneratedResume,
        deleteGeneratedResume,
        currentGeneratedResume,

        // JD Match
        jdMatchResults,
        jdMatchResultsLoading,
        fetchJDMatchResults,
        selectJDMatchResult,
        deleteJDMatchResult: deleteJDMatchResultAction,
        clearJDMatchResult,

        // Common
        setShowAbilityProfile
    } = useInterviewStore();

    const [resumeSubTab, setResumeSubTab] = useState<'analysis' | 'generated' | 'jd-match'>('analysis');
    const [showPreview, setShowPreview] = useState(false);
    const [jdMatchDeleteId, setJDMatchDeleteId] = useState<number | null>(null);

    // 当切换到简历模式时，加载历史记录
    useEffect(() => {
        if (currentView === 'resume') {
            if (resumeResults.length === 0) fetchResumeResults();
            if (generatedResumes.length === 0) fetchGeneratedResumes();
            if (jdMatchResults.length === 0) fetchJDMatchResults();
        }
    }, [currentView, fetchResumeResults, fetchGeneratedResumes, fetchJDMatchResults, resumeResults.length, generatedResumes.length, jdMatchResults.length]);

    const handleSessionSelect = (sessionId: string) => {
        selectSession(sessionId);
        if (window.innerWidth < 768) {
            onClose();
        }
    };

    const handleResumeSelect = (resultId: number) => {
        selectResumeResult(resultId);
        if (window.innerWidth < 768) {
            onClose();
        }
    };

    const handleGeneratedResumeSelect = async (id: number) => {
        await selectGeneratedResume(id);
        setShowPreview(true);
        if (window.innerWidth < 768) {
            onClose();
        }
    };

    const handleJDMatchSelect = async (analysisId: number) => {
        await selectJDMatchResult(analysisId);
        onViewChange('resume');
        if (window.innerWidth < 768) {
            onClose();
        }
    };

    const handleJDMatchDelete = async (analysisId: number) => {
        await deleteJDMatchResultAction(analysisId);
        setJDMatchDeleteId(null);
    };

    const handleNewSession = () => {
        if (currentView === 'interview') {
            createNewSession();
        } else {
            // 简历模式下，新建 = 清空当前选中的结果，回到输入界面
            clearResumeResult();
            clearJDMatchResult();
        }
        if (window.innerWidth < 768) {
            onClose();
        }
    };

    return (
        <>
            <AnimatePresence mode="wait">
                {isOpen && (
                    <motion.aside
                        initial={{ width: 0, opacity: 0 }}
                        animate={{
                            width: 260,
                            opacity: 1,
                            transition: {
                                width: { duration: 0.2, ease: "easeInOut" },
                                opacity: { duration: 0.2 }
                            }
                        }}
                        exit={{
                            width: 0,
                            opacity: 0,
                            transition: {
                                width: { duration: 0.2, ease: "easeInOut" },
                                opacity: { duration: 0.1 }
                            }
                        }}
                        className="flex-shrink-0 h-full relative z-40 bg-[#fefaf6] border-r border-gray-200 flex flex-col"
                    >
                        <div className="flex flex-col">
                            {/* 1. 顶部图标和关闭按钮 */}
                            <div className="px-4 pt-6 pb-2 flex items-center justify-between">
                                <div className="w-10 h-10 relative flex items-center justify-center rounded-xl overflow-hidden">
                                    <Image src="/logo.png" alt="Logo" width={40} height={40} className="object-cover" />
                                </div>
                                <Button
                                    variant="ghost"
                                    size="icon"
                                    onClick={onClose}
                                    className="h-10 w-10 text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded-lg"
                                >
                                    <PanelLeftClose className="w-6 h-6" />
                                </Button>
                            </div>

                            {/* 2. 模式切换 Tabs */}
                            <div className="px-4 pb-4">
                                <Tabs value={currentView} onValueChange={(v) => onViewChange(v as 'interview' | 'resume' | 'questionbank')} className="w-full">
                                    <TabsList className="w-full grid grid-cols-2 bg-orange-100/40 p-1 rounded-lg">
                                        <TabsTrigger
                                            value="interview"
                                            className="text-xs font-medium data-[state=active]:bg-white data-[state=active]:text-orange-700 data-[state=active]:shadow-sm rounded-md transition-all gap-1.5"
                                        >
                                            <MessageCircle size={14} />
                                            模拟面试
                                        </TabsTrigger>
                                        <TabsTrigger
                                            value="resume"
                                            className="text-xs font-medium data-[state=active]:bg-white data-[state=active]:text-orange-700 data-[state=active]:shadow-sm rounded-md transition-all gap-1.5"
                                        >
                                            <FileText size={14} />
                                            简历工具
                                        </TabsTrigger>
                                    </TabsList>
                                </Tabs>
                            </div>

                            {/* 3. 新建按钮 */}
                            <div className="px-4 pb-4">
                                <Button
                                    onClick={handleNewSession}
                                    variant="ghost"
                                    className={cn(
                                        "w-full justify-start gap-3 h-11 rounded-xl bg-[#FFF7ED] hover:bg-[#FFEDD5]",
                                        "text-orange-700 hover:text-orange-900",
                                        "transition-all px-4"
                                    )}
                                >
                                    <Plus className="w-5 h-5 text-orange-600" strokeWidth={2.5} />
                                    <span className="text-[15px] font-semibold tracking-wide">
                                        {currentView === 'interview' ? '新建模拟面试' : '新建简历分析'}
                                    </span>
                                </Button>
                            </div>

                            {/* 4. 分隔线 */}
                            <div className="h-[1px] bg-gray-200 mx-4 mb-2" />
                        </div>

                        {/* 列表区域 */}
                        <div className="flex-1 overflow-hidden px-4 py-2">
                            {currentView === 'interview' ? (
                                <SessionList
                                    sessions={sessions}
                                    onSessionSelect={handleSessionSelect}
                                    onDeleteSession={deleteSession}
                                    onEditSession={updateSessionTitle}
                                    onTogglePin={togglePinSession}
                                    currentSessionId={currentSession?.session_id}
                                    loading={sessionLoading}
                                />
                            ) : (
                                <div className="h-full flex flex-col">
                                    <div className="px-2 mb-2">
                                        <div className="flex p-1 bg-gray-100 rounded-lg">
                                            <button
                                                onClick={() => setResumeSubTab('analysis')}
                                                className={cn(
                                                    "flex-1 text-xs font-medium py-1.5 rounded-md transition-all",
                                                    resumeSubTab === 'analysis' ? "bg-white text-orange-700 shadow-sm" : "text-gray-500 hover:text-gray-700"
                                                )}
                                            >
                                                分析记录
                                            </button>
                                            <button
                                                onClick={() => setResumeSubTab('jd-match')}
                                                className={cn(
                                                    "flex-1 text-xs font-medium py-1.5 rounded-md transition-all",
                                                    resumeSubTab === 'jd-match' ? "bg-white text-orange-700 shadow-sm" : "text-gray-500 hover:text-gray-700"
                                                )}
                                            >
                                                JD 匹配
                                            </button>
                                            <button
                                                onClick={() => setResumeSubTab('generated')}
                                                className={cn(
                                                    "flex-1 text-xs font-medium py-1.5 rounded-md transition-all",
                                                    resumeSubTab === 'generated' ? "bg-white text-orange-700 shadow-sm" : "text-gray-500 hover:text-gray-700"
                                                )}
                                            >
                                                我的简历
                                            </button>
                                        </div>
                                    </div>
                                    <div className="flex-1 overflow-hidden">
                                        {resumeSubTab === 'analysis' ? (
                                            <ResumeHistoryList
                                                results={resumeResults}
                                                onSelect={handleResumeSelect}
                                                onDelete={deleteResumeResult}
                                                currentResultId={currentResumeResult?.id}
                                                loading={resumeResultLoading}
                                            />
                                        ) : resumeSubTab === 'jd-match' ? (
                                            <JDMatchHistoryList
                                                results={jdMatchResults}
                                                onSelect={handleJDMatchSelect}
                                                onDelete={(id) => setJDMatchDeleteId(id)}
                                                loading={jdMatchResultsLoading}
                                            />
                                        ) : (
                                            <GeneratedResumeList
                                                results={generatedResumes}
                                                onSelect={handleGeneratedResumeSelect}
                                                onDelete={deleteGeneratedResume}
                                                currentResultId={currentGeneratedResume?.id}
                                                loading={generatedResumesLoading}
                                            />
                                        )}
                                    </div>
                                </div>
                            )}
                        </div>

                        {/* 底部设置区域 */}
                        <div className="p-4 border-t border-gray-200 space-y-2">
                            {/* 题库入口 */}
                            <Button
                                variant="ghost"
                                className={cn(
                                    "w-full justify-start gap-3 h-10 transition-all",
                                    currentView === 'questionbank'
                                        ? "bg-orange-50 border border-orange-200 text-orange-700 hover:bg-orange-100"
                                        : "text-gray-600 hover:text-gray-900 hover:bg-gray-100"
                                )}
                                onClick={() => {
                                    onViewChange('questionbank' as any);
                                    if (window.innerWidth < 768) onClose();
                                }}
                            >
                                <BookOpen className="w-4 h-4" />
                                <span className="text-sm font-medium">题库</span>
                            </Button>

                            {/* 投递追踪入口 */}
                            <Button
                                variant="ghost"
                                className={cn(
                                    "w-full justify-start gap-3 h-10 transition-all",
                                    currentView === 'applications'
                                        ? "bg-orange-50 border border-orange-200 text-orange-700 hover:bg-orange-100"
                                        : "text-gray-600 hover:text-gray-900 hover:bg-gray-100"
                                )}
                                onClick={() => {
                                    onViewChange('applications');
                                    if (window.innerWidth < 768) onClose();
                                }}
                            >
                                <Briefcase className="w-4 h-4" />
                                <span className="text-sm font-medium">投递追踪</span>
                            </Button>

                            {/* BOSS 半自动化入口 */}
                            <Button
                                variant="ghost"
                                className={cn(
                                    "w-full justify-start gap-3 h-10 transition-all",
                                    currentView === 'boss'
                                        ? "bg-orange-50 border border-orange-200 text-orange-700 hover:bg-orange-100"
                                        : "text-gray-600 hover:text-gray-900 hover:bg-gray-100"
                                )}
                                onClick={() => {
                                    onViewChange('boss' as any);
                                    if (window.innerWidth < 768) onClose();
                                }}
                            >
                                <Briefcase className="w-4 h-4" />
                                <span className="text-sm font-medium">BOSS 半自动化</span>
                            </Button>

                            {/* 能力画像入口 (仅面试模式显示) */}
                            {currentView === 'interview' && (
                                <Button
                                    variant="ghost"
                                    className="w-full justify-start gap-3 h-10 bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-white via-gray-100 to-gray-300 border border-gray-200 text-gray-700 hover:from-gray-50 hover:to-gray-400 hover:text-gray-900 shadow-sm transition-all"
                                    onClick={() => {
                                        setShowAbilityProfile(true);
                                        if (window.innerWidth < 768) onClose();
                                    }}
                                >
                                    <Award className="w-4 h-4 text-orange-500" />
                                    <span className="text-sm font-medium">综合能力画像</span>
                                </Button>
                            )}

                            {/* 设置入口 */}
                            <Button
                                variant="ghost"
                                className="w-full justify-start gap-3 h-10 text-gray-600 hover:text-gray-900 hover:bg-gray-100"
                                onClick={onOpenSettings}
                            >
                                <Settings className="w-4 h-4" />
                                <span className="text-sm font-medium">设置</span>
                            </Button>

                            {/* 用户信息 */}
                            <div className="flex items-center gap-3 px-2 py-2">
                                <Avatar className="h-8 w-8 bg-orange-100 flex items-center justify-center">
                                    <User className="w-5 h-5 text-orange-700" />
                                </Avatar>
                                <div className="flex-1 min-w-0">
                                    <p className="text-sm font-medium text-gray-900 truncate">面试候选人</p>
                                    <p className="text-xs text-gray-500 truncate">Pro Plan</p>
                                </div>
                            </div>
                        </div>
                    </motion.aside>
                )}
            </AnimatePresence>


            <ResumePreviewDialog
                isOpen={showPreview}
                onClose={() => setShowPreview(false)}
                title={currentGeneratedResume?.title || '简历预览'}
                content={currentGeneratedResume?.content || ''}
                onContentChange={async (newContent) => {
                    if (currentGeneratedResume?.id) {
                        await updateGeneratedResume(currentGeneratedResume.id, newContent);
                        fetchGeneratedResumes();
                    }
                }}
            />

            {/* JD 匹配删除确认 */}
            <AlertDialog open={jdMatchDeleteId !== null} onOpenChange={() => setJDMatchDeleteId(null)}>
                <AlertDialogContent className="max-w-md">
                    <AlertDialogHeader>
                        <AlertDialogTitle>删除此记录？</AlertDialogTitle>
                        <AlertDialogDescription>
                            此 JD 匹配分析记录将被永久删除，不可恢复
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogCancel>取消</AlertDialogCancel>
                        <AlertDialogAction
                            onClick={() => jdMatchDeleteId && handleJDMatchDelete(jdMatchDeleteId)}
                            className="bg-red-600 hover:bg-red-700 focus:ring-red-600"
                        >
                            删除
                        </AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </>
    );
}


// ============================================================================
// JD 匹配历史列表组件
// ============================================================================

interface JDMatchHistoryListProps {
    results: Array<{ id: number; resume_source_type: string; job_description: string; created_at: string }>;
    onSelect: (id: number) => void;
    onDelete: (id: number) => void;
    loading?: boolean;
}

function JDMatchHistoryList({ results, onSelect, onDelete, loading }: JDMatchHistoryListProps) {
    if (loading && results.length === 0) {
        return (
            <div className="flex flex-col items-center justify-center h-40 space-y-2">
                <div className="w-4 h-4 border-2 border-gray-300 border-t-transparent rounded-full animate-spin" />
                <div className="text-xs text-gray-400">加载中...</div>
            </div>
        );
    }

    if (results.length === 0) {
        return (
            <div className="flex flex-col items-center justify-center h-40 px-4 text-center">
                <Target className="w-8 h-8 text-gray-300 mb-2" />
                <p className="text-xs text-gray-400">暂无 JD 匹配记录</p>
            </div>
        );
    }

    return (
        <ScrollArea className="h-full">
            <div className="space-y-0.5 px-1">
                {results.map((item) => (
                    <div
                        key={item.id}
                        onClick={() => onSelect(item.id)}
                        className="group flex items-center gap-3 px-3 py-2.5 rounded-lg cursor-pointer transition-all text-sm text-gray-600 hover:bg-gray-100 hover:text-gray-900 w-[226px]"
                    >
                        <Target className="w-4 h-4 flex-shrink-0 text-orange-600" />
                        <div className="flex-1 min-w-0">
                            <div className="truncate leading-none font-medium mb-1">
                                JD 匹配分析
                            </div>
                            <div className="text-[10px] text-gray-400 truncate" title={item.job_description}>
                                {item.job_description.slice(0, 20)}{item.job_description.length > 20 ? '...' : ''}
                            </div>
                        </div>
                        <div className="flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                            <DropdownMenu>
                                <DropdownMenuTrigger asChild onClick={(e) => e.stopPropagation()}>
                                    <Button variant="ghost" size="icon" className="h-6 w-6 p-0 hover:bg-gray-200 rounded-md">
                                        <MoreHorizontal className="w-3.5 h-3.5 text-gray-500" />
                                    </Button>
                                </DropdownMenuTrigger>
                                <DropdownMenuContent align="end" className="w-36">
                                    <DropdownMenuItem
                                        className="text-red-600 focus:text-red-600 focus:bg-red-50"
                                        onClick={(e) => { e.stopPropagation(); onDelete(item.id); }}
                                    >
                                        <Trash2 className="w-3.5 h-3.5 mr-2 text-red-600" />
                                        删除记录
                                    </DropdownMenuItem>
                                </DropdownMenuContent>
                            </DropdownMenu>
                        </div>
                    </div>
                ))}
            </div>
        </ScrollArea>
    );
}


function Award(props: React.SVGProps<SVGSVGElement>) {
    return (
        <svg
            {...props}
            xmlns="http://www.w3.org/2000/svg"
            width="24"
            height="24"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
        >
            <circle cx="12" cy="8" r="7" />
            <polyline points="8.21 13.89 7 23 12 20 17 23 15.79 13.88" />
        </svg>
    )
}
