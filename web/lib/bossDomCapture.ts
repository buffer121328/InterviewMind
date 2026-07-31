import type { BossDomCapturePayload, BossDomJobCard } from "@/lib/api/jobs";

export const BOSS_DOM_CAPTURE_KIND = "interviewmind-boss-dom-capture-v1" as const;

/** Returns true only for official BOSS search pages accepted from the existing-tab bridge. */
export function isBossSearchUrl(value: string): boolean {
    try {
        const url = new URL(value);
        return url.protocol === "https:"
            && (url.hostname === "zhipin.com" || url.hostname.endsWith(".zhipin.com"))
            && ["/web/geek/job", "/web/geek/jobs"].includes(url.pathname.replace(/\/$/, ""));
    } catch {
        return false;
    }
}

/** Returns true only for canonical BOSS job-detail links. */
function isBossJobUrl(value: string): boolean {
    try {
        const url = new URL(value);
        return url.protocol === "https:"
            && (url.hostname === "zhipin.com" || url.hostname.endsWith(".zhipin.com"))
            && /^\/job_detail\/[A-Za-z0-9_-]+\.html$/.test(url.pathname);
    } catch {
        return false;
    }
}

/** Bounds one untrusted browser-bridge field before it reaches React state or the AgentRun request. */
function boundedString(value: unknown, maxLength: number): string {
    return typeof value === "string" ? value.trim().slice(0, maxLength) : "";
}

/** Keeps only the employee-count fragment when BOSS combines financing, industry and scale tags. */
function normalizeCompanySizeText(value: unknown): string {
    const normalized = boundedString(value, 200).replace(/\s+/g, " ");
    return normalized.match(/(?:少于)?\d{1,6}(?:-\d{1,6})?人(?:以上|以下)?|\d+(?:\.\d+)?万人(?:以上|以下)?/)?.[0] ?? "";
}

/** Parses and validates one current-page capture without accepting HTML, cookies or arbitrary URLs. */
export function parseBossDomCapturePayload(input: unknown): BossDomCapturePayload {
    const raw = typeof input === "string" ? JSON.parse(input) as unknown : input;
    if (typeof raw !== "object" || raw === null) {
        throw new Error("采集内容不是有效 JSON 对象");
    }
    const record = raw as Record<string, unknown>;
    if (record.kind !== BOSS_DOM_CAPTURE_KIND) {
        throw new Error("浏览器桥接返回的数据版本不匹配，请刷新后重试");
    }
    const sourcePageUrl = boundedString(record.source_page_url, 2048);
    if (!isBossSearchUrl(sourcePageUrl)) {
        throw new Error("仅支持 BOSS 官方岗位搜索页");
    }
    if (!Array.isArray(record.cards) || record.cards.length < 1 || record.cards.length > 20) {
        throw new Error("当前页岗位卡片数量必须为 1–20 张");
    }

    const cards: BossDomJobCard[] = [];
    record.cards.forEach((item, index) => {
        if (typeof item !== "object" || item === null) {
            throw new Error(`第 ${index + 1} 张岗位卡片格式无效`);
        }
        const cardRecord = item as Record<string, unknown>;
        const card: BossDomJobCard = {
            company_name: boundedString(cardRecord.company_name, 200),
            company_size_text: normalizeCompanySizeText(cardRecord.company_size_text),
            job_title: boundedString(cardRecord.job_title, 200),
            salary_text: boundedString(cardRecord.salary_text, 100),
            city: boundedString(cardRecord.city, 100),
            title_summary: boundedString(cardRecord.title_summary, 300),
            job_description: boundedString(cardRecord.job_description, 3000),
            source_url: boundedString(cardRecord.source_url, 2048),
        };
        const internshipText = `${card.job_title} ${card.title_summary} ${card.job_description}`.toLocaleLowerCase();
        if (/实习|实习生|internship|\bintern\b/i.test(internshipText)) return;
        if (
            !card.job_title
            || card.job_description.length < 8
            || (!card.company_name && !card.salary_text)
            || !isBossJobUrl(card.source_url)
        ) {
            throw new Error(`第 ${index + 1} 张岗位卡片缺少有效标题、描述或详情链接`);
        }
        cards.push(card);
    });
    if (cards.length < 1) {
        throw new Error("当前页没有可导入的非实习岗位");
    }

    return {
        kind: BOSS_DOM_CAPTURE_KIND,
        source_page_url: sourcePageUrl,
        captured_at: boundedString(record.captured_at, 64) || new Date().toISOString(),
        cards,
    };
}
