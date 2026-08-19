"use client";

import { useMemo, useState } from 'react';
import { Trash2, MoreHorizontal, Edit2, Pin, PinOff, Mic, Eye, ChevronDown, ChevronRight, Building2 } from 'lucide-react';
import { SessionListItem } from '@/store/useInterviewStore';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { cn } from '@/lib/utils';
import { groupInterviewSeries, type InterviewSeriesGroup } from '@/lib/interviewSeries';
import { shouldOpenSessionDeleteConfirmation } from '@/lib/sessionDeleteInteraction';
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    DropdownMenuSeparator,
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

interface SessionListProps {
    sessions: SessionListItem[];
    onSessionSelect: (sessionId: string) => void;
    onDeleteSession: (sessionId: string) => void;
    onEditSession?: (sessionId: string, newTitle: string) => void;
    onTogglePin?: (sessionId: string, pinned: boolean) => void;
    onViewDetails?: (sessionId: string) => void;
    currentSessionId?: string;
    loading?: boolean;
    hasMore?: boolean;
    onLoadMore?: () => void;
}

/** Renders the session list UI and coordinates its typed props, local state, and approved backend interactions. */
export function SessionList({
    sessions,
    onSessionSelect,
    onDeleteSession,
    onEditSession,
    onTogglePin,
    onViewDetails,
    currentSessionId,
    loading,
    hasMore,
    onLoadMore,
}: SessionListProps) {

    /** Handles delete; updates local UI state first and delegates server mutations through the approved API boundary. */
    const handleDelete = async (sessionId: string) => {
        await onDeleteSession(sessionId);
    };

    // 先按显式 series_id 聚合公司，再按公司系列最近更新时间分日期。
    const groupedSessions = useMemo(() => {
        const groups: Record<string, InterviewSeriesGroup<SessionListItem>[]> = {
            '今天': [], '昨天': [], '过去7天': [], '更早': [],
        };
        const now = new Date();
        const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
        const yesterday = today - 86400000;
        const lastWeek = today - 86400000 * 7;
        groupInterviewSeries(sessions).forEach(series => {
            const date = new Date(series.updatedAt).getTime();
            if (date >= today) groups['今天'].push(series);
            else if (date >= yesterday) groups['昨天'].push(series);
            else if (date >= lastWeek) groups['过去7天'].push(series);
            else groups['更早'].push(series);
        });
        return groups;
    }, [sessions]);

    if (loading && sessions.length === 0) {
        return (
            <div className="flex flex-col items-center justify-center h-40 space-y-2">
                <div className="w-4 h-4 border-2 border-gray-300 border-t-transparent rounded-full animate-spin" />
                <div className="text-xs text-gray-400">加载中...</div>
            </div>
        );
    }

    if (sessions.length === 0) {
        return (
            <div className="flex flex-col items-center justify-center h-40 px-4 text-center">
                <p className="text-xs text-gray-400">暂无历史会话</p>
            </div>
        );
    }

    return (
        <ScrollArea className="h-full">
            <div className="space-y-4">
                {Object.entries(groupedSessions).map(([group, groupSessions]) => (
                    groupSessions.length > 0 && (
                        <div key={group}>
                            <h4 className="px-3 mb-1 text-[11px] font-medium text-gray-400">
                                {group}
                            </h4>
                            <div className="space-y-0.5">
                                {groupSessions.map((series) => (
                                    <SeriesItem
                                        key={series.key}
                                        series={series}
                                        currentSessionId={currentSessionId}
                                        onSessionSelect={onSessionSelect}
                                        onDeleteSession={handleDelete}
                                        onEdit={onEditSession}
                                        onTogglePin={onTogglePin}
                                        onViewDetails={onViewDetails}
                                    />
                                ))}
                            </div>
                        </div>
                    )
                ))}
                {hasMore && (
                    <Button variant="outline" size="sm" className="mx-3 w-[calc(100%_-_1.5rem)]" onClick={onLoadMore} disabled={loading}>
                        {loading ? '加载中...' : '加载更多'}
                    </Button>
                )}
            </div>
        </ScrollArea>
    );
}

interface SeriesItemProps {
    series: InterviewSeriesGroup<SessionListItem>;
    currentSessionId?: string;
    onSessionSelect: (sessionId: string) => void;
    onDeleteSession: (sessionId: string) => void;
    onEdit?: (sessionId: string, newTitle: string) => void;
    onTogglePin?: (sessionId: string, pinned: boolean) => void;
    onViewDetails?: (sessionId: string) => void;
}

/** Renders one explicitly linked company series and keeps later rounds behind a local disclosure control. */
function SeriesItem({ series, currentSessionId, onSessionSelect, onDeleteSession, onEdit, onTogglePin, onViewDetails }: SeriesItemProps) {
    const [expanded, setExpanded] = useState(series.rounds.some(item => item.session_id === currentSessionId));
    const root = series.rounds[0];
    const childRounds = series.rounds.slice(1);
    if (childRounds.length === 0) {
        return <SessionItem session={root} isActive={root.session_id === currentSessionId} onSelect={() => onSessionSelect(root.session_id)} onDelete={() => onDeleteSession(root.session_id)} onEdit={onEdit} onTogglePin={onTogglePin} onViewDetails={onViewDetails} />;
    }
    return (
        <div className="rounded-lg border border-transparent bg-white/40">
            <div className="flex items-center">
                <button type="button" aria-label={expanded ? '收起公司面试轮次' : '展开公司面试轮次'} onClick={() => setExpanded(value => !value)} className="ml-1 rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-teal-600">
                    {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                </button>
                <div className="min-w-0 flex-1">
                    <SessionItem session={{ ...root, title: series.companyLabel }} isActive={root.session_id === currentSessionId} onSelect={() => onSessionSelect(root.session_id)} onDelete={() => onDeleteSession(root.session_id)} onEdit={onEdit} onTogglePin={onTogglePin} onViewDetails={onViewDetails} leadingIcon={<Building2 className="h-3.5 w-3.5 text-teal-600" />} />
                </div>
            </div>
            {expanded && (
                <div className="ml-5 border-l border-teal-100 pl-2">
                    {childRounds.map(round => <SessionItem key={round.session_id} session={round} isActive={round.session_id === currentSessionId} onSelect={() => onSessionSelect(round.session_id)} onDelete={() => onDeleteSession(round.session_id)} onEdit={onEdit} onTogglePin={onTogglePin} onViewDetails={onViewDetails} nested />)}
                </div>
            )}
        </div>
    );
}

interface SessionItemProps {
    session: SessionListItem;
    isActive: boolean;
    onSelect: () => void;
    onDelete: () => void;
    onEdit?: (sessionId: string, newTitle: string) => void;
    onTogglePin?: (sessionId: string, pinned: boolean) => void;
    onViewDetails?: (sessionId: string) => void;
    nested?: boolean;
    leadingIcon?: React.ReactNode;
}

/** Encapsulates session item; returns typed data or state and keeps side effects within the owning module boundary. */
function SessionItem({ session, isActive, onSelect, onDelete, onEdit, onTogglePin, onViewDetails, nested = false, leadingIcon }: SessionItemProps) {
    const [isEditing, setIsEditing] = useState(false);
    const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
    const [editTitle, setEditTitle] = useState(session.title);
    // 移除可能存在的"职位名称："前缀，保持整洁
    const displayTitle = (session.title || "模拟面试").replace('职位名称：', '').replace('职位名称:', '');

    /** Handles edit; updates local UI state first and delegates server mutations through the approved API boundary. */
    const handleEdit = (e: React.MouseEvent) => {
        e.stopPropagation();
        setEditTitle(displayTitle);
        setIsEditing(true);
    };

    /** Handles save edit; updates local UI state first and delegates server mutations through the approved API boundary. */
    const handleSaveEdit = () => {
        if (editTitle.trim() && onEdit) {
            onEdit(session.session_id, editTitle.trim());
        }
        setIsEditing(false);
    };

    /** Handles cancel edit; updates local UI state first and delegates server mutations through the approved API boundary. */
    const handleCancelEdit = () => {
        setEditTitle(displayTitle);
        setIsEditing(false);
    };

    /** Handles toggle pin; updates local UI state first and delegates server mutations through the approved API boundary. */
    const handleTogglePin = (e: React.MouseEvent) => {
        e.stopPropagation();
        if (onTogglePin) {
            onTogglePin(session.session_id, !session.pinned);
        }
    };

    /** Handles delete click; updates local UI state first and delegates server mutations through the approved API boundary. */
    const handleDeleteClick = (e: React.MouseEvent) => {
        e.stopPropagation();
        setIsDeleteDialogOpen(true);
    };

    /** Opens the protected deletion confirmation from a deliberate right-click. */
    const handleContextMenu = (e: React.MouseEvent) => {
        if (!shouldOpenSessionDeleteConfirmation(e.button)) return;
        e.preventDefault();
        e.stopPropagation();
        setIsDeleteDialogOpen(true);
    };

    /** Handles view details; updates local UI state first and delegates server mutations through the approved API boundary. */
    const handleViewDetails = (e: React.MouseEvent) => {
        e.stopPropagation();
        onViewDetails?.(session.session_id);
    };

    /** Handles confirm delete; updates local UI state first and delegates server mutations through the approved API boundary. */
    const handleConfirmDelete = () => {
        onDelete();
        setIsDeleteDialogOpen(false);
    };

    return (
        <div
            onClick={onSelect}
            onContextMenu={handleContextMenu}
            className={cn(
                "group flex items-center gap-3 px-3 py-2.5 rounded-lg cursor-pointer transition-all text-sm w-full",
                nested && "py-2 pl-2 text-xs",
                isActive
                    ? "bg-gray-200/60 text-gray-900 font-medium"
                    : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
            )}
        >

            {leadingIcon}
            {/* 置顶标识 */}
            {session.pinned && (
                <Pin className="w-3.5 h-3.5 text-orange-600 flex-shrink-0" fill="currentColor" />
            )}

            {/* 标题和轮次徽章 */}
            <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5">
                    <div className="truncate leading-none font-medium flex-1" title={displayTitle}>
                        {displayTitle}
                    </div>
                    {session.mode === 'voice' && (
                        <Mic className="w-3 h-3 text-purple-500 flex-shrink-0" />
                    )}
                    {session.round_index && session.round_index > 1 && (
                        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-orange-100 text-orange-700 flex-shrink-0">
                            第{session.round_index}轮
                        </span>
                    )}
                </div>
            </div>

            {/* 更多操作 (悬停显示) */}
            <div className={cn(
                "flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity",
                isActive && "opacity-100" // 选中时如果需要也可以一直显示，或者保持hover显示
            )}>
                <DropdownMenu>
                    <DropdownMenuTrigger asChild onClick={(e) => e.stopPropagation()}>
                        <Button
                            variant="ghost"
                            size="icon"
                            className="h-6 w-6 p-0 hover:bg-gray-200 rounded-md"
                        >
                            <MoreHorizontal className="w-3.5 h-3.5 text-gray-500" />
                        </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-36">
                        {onViewDetails && (
                            <DropdownMenuItem onClick={handleViewDetails}>
                                <Eye className="w-3.5 h-3.5 mr-2" />
                                查看详情
                            </DropdownMenuItem>
                        )}
                        <DropdownMenuItem
                            onClick={handleEdit}
                        >
                            <Edit2 className="w-3.5 h-3.5 mr-2" />
                            编辑标题
                        </DropdownMenuItem>
                        <DropdownMenuItem
                            onClick={handleTogglePin}
                        >
                            {session.pinned ? (
                                <>
                                    <PinOff className="w-3.5 h-3.5 mr-2" />
                                    取消置顶
                                </>
                            ) : (
                                <>
                                    <Pin className="w-3.5 h-3.5 mr-2" />
                                    置顶
                                </>
                            )}
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                            className="text-red-600 focus:text-red-600 focus:bg-red-50"
                            onClick={handleDeleteClick}
                        >
                            <Trash2 className="w-3.5 h-3.5 mr-2 text-red-600" />
                            删除会话
                        </DropdownMenuItem>
                    </DropdownMenuContent>
                </DropdownMenu>
            </div>

            {/* 编辑对话框 */}
            {isEditing && (
                <div
                    className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
                    onClick={handleCancelEdit}
                >
                    <div
                        className="bg-white rounded-xl p-6 w-96 shadow-xl"
                        onClick={(e) => e.stopPropagation()}
                    >
                        <h3 className="text-lg font-semibold mb-4">编辑会话标题</h3>
                        <input
                            type="text"
                            value={editTitle}
                            onChange={(e) => setEditTitle(e.target.value)}
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500 mb-4"
                            autoFocus
                            onKeyDown={(e) => {
                                if (e.key === 'Enter') handleSaveEdit();
                                if (e.key === 'Escape') handleCancelEdit();
                            }}
                        />
                        <div className="flex gap-2 justify-end">
                            <Button
                                variant="outline"
                                onClick={handleCancelEdit}
                            >
                                取消
                            </Button>
                            <Button
                                onClick={handleSaveEdit}
                                className="bg-orange-600 hover:bg-orange-700"
                            >
                                确认
                            </Button>
                        </div>
                    </div>
                </div>
            )}

            {/* 删除确认对话框 */}
            <AlertDialog open={isDeleteDialogOpen} onOpenChange={setIsDeleteDialogOpen}>
                <AlertDialogContent className="max-w-md" onClick={(e) => e.stopPropagation()}>
                    <AlertDialogHeader>
                        <AlertDialogTitle>删除此会话？</AlertDialogTitle>
                        <AlertDialogDescription>
                            这条会话的回答、单轮画像、报告和会话文件将被永久删除，且不可恢复。
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogCancel onClick={(e) => e.stopPropagation()}>取消</AlertDialogCancel>
                        <AlertDialogAction
                            onClick={(e) => {
                                e.stopPropagation();
                                handleConfirmDelete();
                            }}
                            className="bg-red-600 hover:bg-red-700 focus:ring-red-600"
                        >
                            删除
                        </AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </div>
    );
}
