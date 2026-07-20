"""面经来源适配器。

牛客仅访问固定平台接口；小红书只解析用户授权导出的内容，不接收或保存 Cookie。
"""

import asyncio
import html
import json
import re
from typing import Any

import httpx

from app.schemas.experience_provider import ExperienceDocument


def _plain_text(value: str) -> str:
    value = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", value or "", flags=re.I | re.S)
    value = re.sub(r"<br\s*/?>|</p>|</div>", "\n", value, flags=re.I)
    value = re.sub(r"<[^>]+>", "", value)
    value = html.unescape(value)
    return re.sub(r"\n\s*\n+", "\n\n", value).strip()


class ExportedContentProvider:
    """解析平台导出的 JSON；适用于小红书及后续新增来源。"""

    def __init__(self, source: str):
        self.source = source

    async def collect(
        self,
        *,
        queries: list[str],
        max_pages: int,
        exported_items: list[dict[str, Any]],
    ) -> list[ExperienceDocument]:
        del max_pages
        default_query = queries[0] if queries else ""
        documents: list[ExperienceDocument] = []
        for index, item in enumerate(exported_items):
            content = _plain_text(str(item.get("content") or item.get("desc") or ""))
            if not content:
                continue
            source_id = str(item.get("id") or item.get("note_id") or f"export-{index + 1}")
            documents.append(
                ExperienceDocument(
                    source=self.source,
                    source_id=source_id,
                    title=str(item.get("title") or "未命名面经").strip(),
                    content=content,
                    url=str(item.get("url") or "").strip(),
                    query=str(item.get("query") or item.get("keyword") or default_query).strip(),
                )
            )
        return documents


class NowcoderProvider:
    """牛客公开搜索接口适配器，带页数上限、超时和请求间隔。"""

    source = "nowcoder"
    search_api = "https://gw-c.nowcoder.com/api/sparta/pc/search"
    detail_api = "https://gw-c.nowcoder.com/api/sparta/detail/content-data/detail"
    feed_url = "https://www.nowcoder.com/feed/main/detail"
    max_documents_per_run = 50

    def __init__(self, client: httpx.AsyncClient | None = None, delay_seconds: float = 0.8):
        self._client = client
        self.delay_seconds = max(0.0, delay_seconds)

    async def collect(
        self,
        *,
        queries: list[str],
        max_pages: int,
        exported_items: list[dict[str, Any]],
    ) -> list[ExperienceDocument]:
        if exported_items:
            return await ExportedContentProvider(self.source).collect(
                queries=queries,
                max_pages=max_pages,
                exported_items=exported_items,
            )

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            headers={"User-Agent": "agent-interview/1.0"},
        )
        try:
            records = await self._search(client, queries, min(max_pages, 3))
            documents: list[ExperienceDocument] = []
            for record in list(records.values())[: self.max_documents_per_run]:
                document = await self._fetch_detail(client, record)
                if document and len(document.content) >= 30:
                    documents.append(document)
                if self.delay_seconds:
                    await asyncio.sleep(self.delay_seconds)
            return documents
        finally:
            if owns_client:
                await client.aclose()

    async def _search(
        self,
        client: httpx.AsyncClient,
        queries: list[str],
        max_pages: int,
    ) -> dict[str, dict[str, Any]]:
        records: dict[str, dict[str, Any]] = {}
        for query in queries:
            for page in range(1, max_pages + 1):
                response = await client.post(
                    self.search_api,
                    json={
                        "type": "all",
                        "query": query,
                        "page": page,
                        "tag": [{"name": "面经", "id": 818, "count": None}],
                        "order": "create",
                    },
                )
                response.raise_for_status()
                payload = response.json()
                if not payload.get("success"):
                    break
                page_records = payload.get("data", {}).get("records", [])
                if not page_records:
                    break
                for item in page_records:
                    kind = int(item.get("rc_type") or 0)
                    data = item.get("data") or {}
                    if kind == 207:
                        detail = data.get("contentData") or {}
                        source_id = str(detail.get("id") or "")
                    elif kind == 201:
                        detail = data.get("momentData") or {}
                        source_id = str(detail.get("uuid") or "")
                    else:
                        continue
                    if source_id:
                        records.setdefault(
                            source_id,
                            {"kind": kind, "source_id": source_id, "title": detail.get("title", ""), "query": query},
                        )
                if page >= int(payload.get("data", {}).get("totalPage") or 1):
                    break
                if self.delay_seconds:
                    await asyncio.sleep(self.delay_seconds)
        return records

    async def _fetch_detail(
        self,
        client: httpx.AsyncClient,
        record: dict[str, Any],
    ) -> ExperienceDocument | None:
        source_id = record["source_id"]
        if record["kind"] == 207:
            response = await client.get(f"{self.detail_api}/{source_id}")
            response.raise_for_status()
            payload = response.json()
            if not payload.get("success"):
                return None
            data = payload.get("data") or {}
            content = _plain_text(str(data.get("richText") or data.get("content") or ""))
            title = str(data.get("title") or record.get("title") or "")
            url = f"https://www.nowcoder.com/discuss/{source_id}"
        else:
            response = await client.get(f"{self.feed_url}/{source_id}")
            response.raise_for_status()
            page = response.text
            matches = re.findall(r'"content"\s*:\s*("(?:\\.|[^"\\])*")', page)
            content = ""
            for match in matches:
                try:
                    candidate = _plain_text(json.loads(match))
                except (json.JSONDecodeError, TypeError):
                    continue
                if len(candidate) > len(content):
                    content = candidate
            title = str(record.get("title") or "")
            url = f"{self.feed_url}/{source_id}"
        if not content:
            return None
        return ExperienceDocument(
            source=self.source,
            source_id=source_id,
            title=title,
            content=content,
            url=url,
            query=str(record.get("query") or ""),
        )
