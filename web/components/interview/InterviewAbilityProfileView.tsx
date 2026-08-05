'use client';

import { Award } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { AbilityProfileView } from '@/components/AbilityProfileView';

interface InterviewAbilityProfileViewProps {
    onBack: () => void;
}

/** Renders the ability-profile page with its header and back-to-chat action. */
export function InterviewAbilityProfileView({ onBack }: InterviewAbilityProfileViewProps) {
    return (
        <div className="flex-1 flex flex-col min-h-0 relative overflow-y-auto">
            <div className="border-b border-gray-100 bg-white/80 backdrop-blur-sm sticky top-0 z-10">
                <div className="max-w-5xl mx-auto px-6 py-4 flex items-center gap-4">
                    <Button
                        variant="ghost"
                        size="sm"
                        onClick={onBack}
                        className="gap-2"
                    >
                        <Award className="w-4 h-4" />
                        返回对话
                    </Button>
                    <div className="flex-1">
                        <h2 className="text-lg font-semibold text-gray-900">成长档案</h2>
                        <p className="text-xs text-gray-500">综合画像、来源记录与阶段变化</p>
                    </div>
                </div>
            </div>
            <AbilityProfileView />
        </div>
    );
}
