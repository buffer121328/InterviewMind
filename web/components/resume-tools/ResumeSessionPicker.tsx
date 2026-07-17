import { ChevronDown, ChevronUp, Loader2 } from 'lucide-react';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
interface ResumeSessionPickerProps {
    sessions: Array<{ session_id: string; title: string; round_index: number; message_count: number }>;
    selectedSessions: string[];
    isOpen: boolean;
    isLoading: boolean;
    onToggleOpen: () => void;
    onToggleSession: (sessionId: string) => void;
}

export function ResumeSessionPicker({
    sessions,
    selectedSessions,
    isOpen,
    isLoading,
    onToggleOpen,
    onToggleSession,
}: ResumeSessionPickerProps) {
    return (
        <div className="space-y-3">
            <div
                className="flex items-center justify-between cursor-pointer p-2 rounded-lg hover:bg-gray-50 transition-colors"
                onClick={onToggleOpen}
            >
                <Label className="cursor-pointer">关联面试记录（可选）</Label>
                <div className="flex items-center gap-2">
                    {selectedSessions.length > 0 && (
                        <span className="text-sm text-gray-500">
                            已选 {selectedSessions.length}/3
                        </span>
                    )}
                    {isOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                </div>
            </div>

            {isOpen && (
                <div className="border rounded-lg p-3 space-y-2 max-h-48 overflow-y-auto">
                    {isLoading ? (
                        <div className="flex items-center justify-center py-4">
                            <Loader2 className="animate-spin" size={20} />
                        </div>
                    ) : sessions.length === 0 ? (
                        <p className="text-sm text-gray-500 text-center py-4">
                            暂无已完成的面试记录
                        </p>
                    ) : (
                        sessions.map((session) => (
                            <div
                                key={session.session_id}
                                className="flex items-center gap-3 p-2 rounded hover:bg-gray-50 cursor-pointer"
                                onClick={() => onToggleSession(session.session_id)}
                            >
                                <Checkbox
                                    checked={selectedSessions.includes(session.session_id)}
                                    onCheckedChange={() => onToggleSession(session.session_id)}
                                />
                                <div className="flex-1 min-w-0">
                                    <p className="text-sm font-medium truncate">{session.title}</p>
                                    <p className="text-xs text-gray-500">
                                        第{session.round_index}轮 · {session.message_count} 条消息
                                    </p>
                                </div>
                            </div>
                        ))
                    )}
                </div>
            )}
        </div>
    );
}
