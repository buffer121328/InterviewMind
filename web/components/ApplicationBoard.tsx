"use client";

import { useMemo, useState } from "react";
import { Loader2, Plus, Search, Trash2 } from "lucide-react";
import { useInterviewStore } from "@/store/useInterviewStore";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

type StatusFilter = undefined | "saved" | "applied" | "interview" | "offer" | "rejected" | "accepted";
type Priority = "high" | "medium" | "low";

interface ApplicationBoardProps {
  onOpenDetail: (applicationId: number) => void;
}

const statusOptions: Array<{ value: StatusFilter; label: string }> = [
  { value: undefined, label: "全部" },
  { value: "saved", label: "已收藏" },
  { value: "applied", label: "已投递" },
  { value: "interview", label: "面试中" },
  { value: "offer", label: "Offer" },
  { value: "rejected", label: "已拒绝" },
  { value: "accepted", label: "已接受" },
];

const statusMeta: Record<Exclude<StatusFilter, undefined>, { label: string; className: string }> = {
  saved: { label: "已收藏", className: "bg-gray-100 text-gray-700 border-gray-200" },
  applied: { label: "已投递", className: "bg-blue-50 text-blue-700 border-blue-200" },
  interview: { label: "面试中", className: "bg-amber-50 text-amber-700 border-amber-200" },
  offer: { label: "Offer", className: "bg-green-50 text-green-700 border-green-200" },
  rejected: { label: "已拒绝", className: "bg-red-50 text-red-700 border-red-200" },
  accepted: { label: "已接受", className: "bg-emerald-50 text-emerald-700 border-emerald-200" },
};

const priorityMeta: Record<Priority, { label: string; dotClassName: string; textClassName: string }> = {
  high: { label: "高", dotClassName: "bg-red-500", textClassName: "text-red-600" },
  medium: { label: "中", dotClassName: "bg-yellow-500", textClassName: "text-yellow-600" },
  low: { label: "低", dotClassName: "bg-gray-400", textClassName: "text-gray-500" },
};

function formatRelativeTime(input: string) {
  const date = new Date(input);
  const diff = Date.now() - date.getTime();
  const minute = 60 * 1000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (diff < minute) return "刚刚";
  if (diff < hour) return `${Math.floor(diff / minute)} 分钟前`;
  if (diff < day) return `${Math.floor(diff / hour)} 小时前`;
  if (diff < 7 * day) return `${Math.floor(diff / day)} 天前`;
  return date.toLocaleDateString("zh-CN", { month: "short", day: "numeric" });
}

export function ApplicationBoard({ onOpenDetail }: ApplicationBoardProps) {
  const applications = useInterviewStore((s) => s.applications);
  const applicationsLoading = useInterviewStore((s) => s.applicationsLoading);
  const createApplication = useInterviewStore((s) => s.createApplication);
  const deleteApplication = useInterviewStore((s) => s.deleteApplication);
  const fetchApplications = useInterviewStore((s) => s.fetchApplications);

  const [status, setStatus] = useState<StatusFilter>(undefined);
  const [createOpen, setCreateOpen] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ company_name: "", job_title: "", channel: "", priority: "medium" as Priority, notes: "" });

  const filtered = useMemo(
    () => (status ? applications.filter((item) => item.latest_status === status) : applications),
    [applications, status]
  );

  const handleCreate = async () => {
    if (!form.company_name.trim() || !form.job_title.trim()) return;
    setSaving(true);
    const created = await createApplication({
      company_name: form.company_name.trim(),
      job_title: form.job_title.trim(),
      channel: form.channel.trim() || undefined,
      priority: form.priority,
      notes: form.notes.trim() || undefined,
    });
    setSaving(false);
    if (created) {
      setCreateOpen(false);
      setForm({ company_name: "", job_title: "", channel: "", priority: "medium", notes: "" });
      await fetchApplications(status, 100);
    }
  };

  const handleDelete = async (id: number) => {
    setDeletingId(id);
    const ok = await deleteApplication(id);
    setDeletingId(null);
    if (ok) await fetchApplications(status, 100);
  };

  return (
    <div className="flex h-full flex-col gap-4">
      <div className="flex flex-col gap-3 rounded-2xl border bg-white/80 p-4 shadow-sm backdrop-blur-sm">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h3 className="text-base font-semibold text-gray-900">投递记录</h3>
            <p className="text-xs text-gray-500">跟踪每个岗位的状态变化</p>
          </div>
          <Button onClick={() => setCreateOpen(true)} className="bg-orange-600 hover:bg-orange-700">
            <Plus className="mr-2 h-4 w-4" /> 新建投递
          </Button>
        </div>

        <Tabs value={status ?? "all"} onValueChange={(v) => setStatus(v === "all" ? undefined : (v as StatusFilter))}>
          <TabsList className="h-auto flex-wrap justify-start gap-2 bg-transparent p-0">
            {statusOptions.map((opt) => (
              <TabsTrigger
                key={opt.label}
                value={opt.value ?? "all"}
                className="h-8 flex-none rounded-full border border-gray-200 bg-white px-3 text-xs text-gray-600 data-[state=active]:border-orange-200 data-[state=active]:bg-orange-50 data-[state=active]:text-orange-700"
              >
                {opt.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </div>

      <ScrollArea className="flex-1">
        <div className="space-y-3 pr-1">
          {applicationsLoading ? (
            Array.from({ length: 5 }).map((_, i) => (
              <Card key={i} className="border-gray-200 bg-white shadow-sm">
                <CardContent className="p-4">
                  <div className="space-y-3">
                    <Skeleton className="h-5 w-40" />
                    <Skeleton className="h-4 w-28" />
                    <Skeleton className="h-4 w-full" />
                  </div>
                </CardContent>
              </Card>
            ))
          ) : filtered.length === 0 ? (
            <div className="flex min-h-[240px] flex-col items-center justify-center rounded-2xl border border-dashed border-gray-200 bg-white text-center">
              <Search className="mb-3 h-10 w-10 text-orange-500/50" />
              <div className="text-sm font-medium text-gray-900">暂无投递记录</div>
              <div className="mt-1 text-xs text-gray-500">点击右上角按钮创建第一条记录</div>
            </div>
          ) : (
            filtered.map((item) => {
              const statusInfo = statusMeta[item.latest_status as Exclude<StatusFilter, undefined>];
              const priorityInfo = priorityMeta[item.priority as Priority];
              return (
                <Card
                  key={item.id}
                  className="group cursor-pointer border-gray-200 bg-white shadow-sm transition hover:border-orange-200 hover:shadow-md"
                  onClick={() => onOpenDetail(item.id)}
                >
                  <CardContent className="p-4">
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-base font-semibold text-gray-900">{item.company_name}</div>
                        <div className="mt-0.5 truncate text-sm text-gray-600">{item.job_title}</div>
                        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                          <span className={cn("inline-flex items-center rounded-full border px-2 py-0.5", statusInfo.className)}>
                            {statusInfo.label}
                          </span>
                          <span className={cn("inline-flex items-center gap-1.5 rounded-full bg-gray-50 px-2 py-0.5", priorityInfo.textClassName)}>
                            <span className={cn("h-1.5 w-1.5 rounded-full", priorityInfo.dotClassName)} />
                            优先级 {priorityInfo.label}
                          </span>
                          {item.channel ? <span className="rounded-full bg-orange-50 px-2 py-0.5 text-orange-700">{item.channel}</span> : null}
                        </div>
                      </div>
                      <div className="flex flex-col items-end gap-2">
                        <div className="text-xs text-gray-400">{formatRelativeTime(item.updated_at)}</div>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 text-gray-400 opacity-0 transition group-hover:opacity-100 hover:bg-red-50 hover:text-red-600"
                          onClick={(e) => {
                            e.stopPropagation();
                            if (window.confirm(`确认删除「${item.company_name} - ${item.job_title}」？`)) handleDelete(item.id);
                          }}
                          disabled={deletingId === item.id}
                        >
                          {deletingId === item.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                        </Button>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              );
            })
          )}
        </div>
      </ScrollArea>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>新建投递记录</DialogTitle>
            <DialogDescription>快速记录一个新的职位投递。</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-2">
            <div className="grid gap-2">
              <Label htmlFor="company">公司名称 *</Label>
              <Input id="company" value={form.company_name} onChange={(e) => setForm((p) => ({ ...p, company_name: e.target.value }))} />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="title">岗位名称 *</Label>
              <Input id="title" value={form.job_title} onChange={(e) => setForm((p) => ({ ...p, job_title: e.target.value }))} />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="channel">投递渠道</Label>
              <Input id="channel" value={form.channel} onChange={(e) => setForm((p) => ({ ...p, channel: e.target.value }))} />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="priority">优先级</Label>
              <select id="priority" className="h-10 rounded-md border border-input bg-background px-3 text-sm" value={form.priority} onChange={(e) => setForm((p) => ({ ...p, priority: e.target.value as Priority }))}>
                <option value="high">高</option>
                <option value="medium">中</option>
                <option value="low">低</option>
              </select>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="notes">备注</Label>
              <Textarea id="notes" value={form.notes} onChange={(e) => setForm((p) => ({ ...p, notes: e.target.value }))} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>取消</Button>
            <Button className="bg-orange-600 hover:bg-orange-700" onClick={handleCreate} disabled={saving || !form.company_name.trim() || !form.job_title.trim()}>
              {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              创建
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
