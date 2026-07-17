import { BarChart3, FileText, Target } from 'lucide-react';

type EmptyStateType = 'analyze' | 'optimize' | 'jd-match';

const COPY: Record<EmptyStateType, { title: string; description: string }> = {
    analyze: {
        title: '准备进行竞争力分析',
        description: '请在左侧填写简历内容，我们将在多维度为您评估简历竞争力。',
    },
    optimize: {
        title: '准备进行内容优化',
        description: '请在左侧填写简历和目标JD，我们将为您提供针对性的优化建议。',
    },
    'jd-match': {
        title: '准备进行 JD 匹配分析',
        description: '在左侧填写简历和目标 JD，快速了解匹配程度和改进方向。',
    },
};

export function ResumeToolEmptyState({ type }: { type: EmptyStateType }) {
    const Icon = type === 'analyze' ? BarChart3 : type === 'optimize' ? FileText : Target;
    const copy = COPY[type];

    return (
        <div className="h-full flex flex-col items-center justify-center text-gray-400 p-8 text-center bg-gray-50/50 rounded-xl border border-dashed border-gray-200">
            <div className="w-16 h-16 bg-white rounded-full flex items-center justify-center mb-4 shadow-sm border border-gray-100">
                <Icon size={32} className="text-orange-500" />
            </div>
            <h3 className="text-lg font-medium text-gray-600 mb-2">{copy.title}</h3>
            <p className="text-sm text-gray-500 max-w-xs leading-relaxed">{copy.description}</p>
        </div>
    );
}
