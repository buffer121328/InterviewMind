'use client';

import { useState, useEffect, useCallback } from 'react';
import {
    Loader2,
    Plus,
    Search,
    Trash2,
    BookOpen,
    ChevronDown,
    ChevronUp,
} from 'lucide-react';
import {
    listQuestionBank,
    createQuestionItem,
    deleteQuestionItem,
    searchQuestionBank,
    type QuestionBankItem,
    type QuestionBankCreateRequest
} from '@/lib/api/questionBank';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Textarea } from './ui/textarea';
import { cn } from '@/lib/utils';
import { toast } from 'sonner';

const DIFFICULTY_STYLES: Record<string, { bg: string; text: string; label: string }> = {
    easy: { bg: 'bg-emerald-100', text: 'text-emerald-700', label: '简单' },
    medium: { bg: 'bg-amber-100', text: 'text-amber-700', label: '中等' },
    hard: { bg: 'bg-red-100', text: 'text-red-700', label: '困难' },
};

const TYPE_LABELS: Record<string, string> = {
    intro: '自我介绍',
    tech: '技术题',
    behavior: '行为题',
    system_design: '系统设计',
};

export function QuestionBankPanel() {
    const [items, setItems] = useState<QuestionBankItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [searchQuery, setSearchQuery] = useState('');
    const [filterType, setFilterType] = useState<string>('');
    const [filterDifficulty, setFilterDifficulty] = useState<string>('');
    const [showAddForm, setShowAddForm] = useState(false);
    const [expandedItems, setExpandedItems] = useState<Set<number>>(new Set());
    const [newQuestion, setNewQuestion] = useState<QuestionBankCreateRequest>({
        question_text: '',
        reference_answer: '',
        tags: [],
        difficulty: 'medium',
        question_type: 'tech'
    });

    const loadItems = useCallback(async () => {
        setLoading(true);
        const response = await listQuestionBank({ question_type: filterType || undefined, difficulty: filterDifficulty || undefined, limit: 100 });
        if (response.success) setItems(response.items);
        setLoading(false);
    }, [filterDifficulty, filterType]);

    useEffect(() => {
        void Promise.resolve().then(() => loadItems());
    }, [loadItems]);

    async function handleSearch() {
        if (!searchQuery.trim()) return loadItems();
        setLoading(true);
        const response = await searchQuestionBank(searchQuery);
        if (response.success) setItems(response.items);
        setLoading(false);
    }

    async function handleCreate() {
        if (!newQuestion.question_text.trim()) return toast.error('请输入题目内容');
        const response = await createQuestionItem(newQuestion);
        if (response.success) {
            toast.success('题目已添加');
            setNewQuestion({ question_text: '', reference_answer: '', tags: [], difficulty: 'medium', question_type: 'tech' });
            setShowAddForm(false);
            loadItems();
        } else toast.error(response.message || '添加失败');
    }

    async function handleDelete(itemId: number) {
        if (!confirm('确定删除此题目？')) return;
        const response = await deleteQuestionItem(itemId);
        if (response.success) {
            toast.success('已删除');
            setItems(prev => prev.filter(i => i.id !== itemId));
        } else toast.error(response.message || '删除失败');
    }

    function toggleExpanded(itemId: number) {
        setExpandedItems(prev => {
            const next = new Set(prev);
            if (next.has(itemId)) {
                next.delete(itemId);
            } else {
                next.add(itemId);
            }
            return next;
        });
    }

    return (
        <div className="h-full flex flex-col">
            <div className="flex items-center justify-between p-4 border-b border-gray-200">
                <div className="flex items-center gap-3">
                    <div className="w-10 h-10 bg-purple-100 rounded-xl flex items-center justify-center"><BookOpen className="w-5 h-5 text-purple-600" /></div>
                    <div><h2 className="text-lg font-bold text-gray-900">题库</h2><p className="text-xs text-gray-500">{items.length} 道题目</p></div>
                </div>
                <Button onClick={() => setShowAddForm(!showAddForm)} className="bg-purple-600 hover:bg-purple-700 text-white" size="sm"><Plus className="w-4 h-4 mr-1" />添加题目</Button>
            </div>
            {showAddForm && <div className="p-4 bg-purple-50 border-b border-purple-100 space-y-3"><Textarea placeholder="输入题目内容..." value={newQuestion.question_text} onChange={(e) => setNewQuestion(prev => ({ ...prev, question_text: e.target.value }))} className="min-h-[80px]" /><Textarea placeholder="参考答案（可选）..." value={newQuestion.reference_answer || ''} onChange={(e) => setNewQuestion(prev => ({ ...prev, reference_answer: e.target.value }))} className="min-h-[60px]" /><div className="flex gap-2"><select value={newQuestion.difficulty} onChange={(e) => setNewQuestion(prev => ({ ...prev, difficulty: e.target.value }))} className="px-3 py-1.5 text-sm border border-gray-200 rounded-lg"><option value="easy">简单</option><option value="medium">中等</option><option value="hard">困难</option></select><select value={newQuestion.question_type} onChange={(e) => setNewQuestion(prev => ({ ...prev, question_type: e.target.value }))} className="px-3 py-1.5 text-sm border border-gray-200 rounded-lg"><option value="tech">技术题</option><option value="intro">自我介绍</option><option value="behavior">行为题</option><option value="system_design">系统设计</option></select><Button onClick={handleCreate} size="sm" className="bg-purple-600 hover:bg-purple-700">保存</Button><Button onClick={() => setShowAddForm(false)} variant="outline" size="sm">取消</Button></div></div>}
            <div className="p-4 border-b border-gray-100 space-y-2">
                <div className="flex gap-2"><Input placeholder="搜索题目..." value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && handleSearch()} className="flex-1" /><Button onClick={handleSearch} variant="outline" size="sm"><Search className="w-4 h-4" /></Button></div>
                <div className="flex gap-2"><select value={filterType} onChange={(e) => setFilterType(e.target.value)} className="px-2 py-1 text-xs border border-gray-200 rounded-lg"><option value="">全部类型</option><option value="tech">技术题</option><option value="intro">自我介绍</option><option value="behavior">行为题</option><option value="system_design">系统设计</option></select><select value={filterDifficulty} onChange={(e) => setFilterDifficulty(e.target.value)} className="px-2 py-1 text-xs border border-gray-200 rounded-lg"><option value="">全部难度</option><option value="easy">简单</option><option value="medium">中等</option><option value="hard">困难</option></select></div>
            </div>
            <div className="flex-1 overflow-y-auto p-4 space-y-2">
                {loading ? <div className="flex items-center justify-center py-12"><Loader2 className="w-6 h-6 text-purple-600 animate-spin" /></div> : items.length === 0 ? <div className="text-center py-12 text-gray-500"><BookOpen className="w-8 h-8 mx-auto mb-2 text-gray-400" /><p className="text-sm">暂无题目</p></div> : items.map((item) => { const diffStyle = DIFFICULTY_STYLES[item.difficulty] || DIFFICULTY_STYLES.medium; const isExpanded = expandedItems.has(item.id); return (<div key={item.id} className="bg-white rounded-xl border border-gray-200 overflow-hidden hover:shadow-sm transition-all"><button onClick={() => toggleExpanded(item.id)} className="w-full px-4 py-3 flex items-center justify-between text-left hover:bg-gray-50 transition-colors"><div className="flex-1 min-w-0"><p className="text-sm font-medium text-gray-900 truncate">{item.question_text}</p><div className="flex items-center gap-2 mt-1"><span className={cn('text-xs px-2 py-0.5 rounded-full', diffStyle.bg, diffStyle.text)}>{diffStyle.label}</span><span className="text-xs text-gray-500">{TYPE_LABELS[item.question_type] || item.question_type}</span>{item.source_type === 'generated' && (<span className="text-xs text-blue-500">AI生成</span>)}</div></div>{isExpanded ? <ChevronUp className="w-4 h-4 text-gray-400 flex-shrink-0 ml-2" /> : <ChevronDown className="w-4 h-4 text-gray-400 flex-shrink-0 ml-2" />}</button>{isExpanded && (<div className="px-4 pb-4 space-y-3 border-t border-gray-100 pt-3">{item.reference_answer && (<div><p className="text-xs font-medium text-gray-500 mb-1">参考答案</p><p className="text-sm text-gray-700 bg-gray-50 rounded-lg p-3">{item.reference_answer}</p></div>)}{item.tags.length > 0 && (<div className="flex flex-wrap gap-1">{item.tags.map((tag, i) => (<span key={i} className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded">{tag}</span>))}</div>)}<div className="flex items-center justify-between text-xs text-gray-500"><span>使用 {item.usage_count} 次</span><Button onClick={() => handleDelete(item.id)} variant="ghost" size="sm" className="text-red-500 hover:text-red-700 hover:bg-red-50"><Trash2 className="w-3 h-3 mr-1" />删除</Button></div></div>)}</div>); })}
            </div>
        </div>
    );
}
