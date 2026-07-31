import assert from "node:assert/strict";
import test from "node:test";

import {
    BOSS_DOM_CAPTURE_KIND,
    isBossSearchUrl,
    parseBossDomCapturePayload,
} from "./bossDomCapture.ts";

const validCard = {
    company_name: "示例科技",
    company_size_text: "100-499人",
    job_title: "Agent 工程师",
    salary_text: "20-30K",
    city: "深圳",
    title_summary: "3-5年 本科",
    job_description: "负责 Agent 产品及 Python 服务端开发工作",
    source_url: "https://www.zhipin.com/job_detail/93dfe9e21580159c0nF_0ti6-FFdY.html",
};

test("accepts one bounded capture returned by the existing browser-tab bridge", () => {
    const payload = parseBossDomCapturePayload(JSON.stringify({
        kind: BOSS_DOM_CAPTURE_KIND,
        source_page_url: "https://www.zhipin.com/web/geek/jobs?city=101280600&query=agent",
        captured_at: "2026-07-30T00:00:00.000Z",
        cards: [validCard],
    }));

    assert.equal(payload.cards.length, 1);
    assert.equal(payload.cards[0].job_title, "Agent 工程师");
    assert.equal(payload.cards[0].company_size_text, "100-499人");
    assert.match(payload.cards[0].source_url, /_0ti6-FFdY\.html$/);
});

test("keeps only the employee-count fragment from mixed company metadata", () => {
    const payload = parseBossDomCapturePayload({
        kind: BOSS_DOM_CAPTURE_KIND,
        source_page_url: "https://www.zhipin.com/web/geek/jobs?query=agent",
        cards: [{ ...validCard, company_size_text: "已上市 人工智能 1000-9999人" }],
    });

    assert.equal(payload.cards[0].company_size_text, "1000-9999人");
});

test("rejects external job links and more than twenty cards", () => {
    assert.throws(() => parseBossDomCapturePayload({
        kind: BOSS_DOM_CAPTURE_KIND,
        source_page_url: "https://www.zhipin.com/web/geek/jobs?query=agent",
        cards: [{ ...validCard, source_url: "https://example.com/job_detail/abc123.html" }],
    }), /详情链接/);
    assert.throws(() => parseBossDomCapturePayload({
        kind: BOSS_DOM_CAPTURE_KIND,
        source_page_url: "https://www.zhipin.com/web/geek/jobs?query=agent",
        cards: Array.from({ length: 21 }, () => validCard),
    }), /1–20/);
    assert.throws(() => parseBossDomCapturePayload({
        kind: BOSS_DOM_CAPTURE_KIND,
        source_page_url: "https://www.zhipin.com/web/geek/jobs?query=agent",
        cards: [{ ...validCard, company_name: "", salary_text: "" }],
    }), /缺少有效/);
});

test("accepts only official BOSS search pages", () => {
    assert.equal(isBossSearchUrl("https://www.zhipin.com/web/geek/jobs?query=agent"), true);
    assert.equal(isBossSearchUrl("https://www.zhipin.com/web/user/"), false);
    assert.equal(isBossSearchUrl("https://example.com/web/geek/jobs?query=agent"), false);
});


test("filters internship cards and preserves a bounded visible job description", () => {
    const longDescription = `负责正式岗位的 Agent 平台开发${"与业务协作".repeat(600)}`;
    const payload = parseBossDomCapturePayload({
        kind: BOSS_DOM_CAPTURE_KIND,
        source_page_url: "https://www.zhipin.com/web/geek/jobs?query=agent",
        cards: [
            { ...validCard, job_title: "Agent 实习生" },
            { ...validCard, job_description: longDescription },
        ],
    });

    assert.equal(payload.cards.length, 1);
    assert.equal(payload.cards[0].job_description.length, 3000);
});
