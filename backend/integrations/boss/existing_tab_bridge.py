"""复用用户已打开的 Chrome/Edge BOSS 标签页完成保守搜索与有限字段采集。

该桥接只调用浏览器官方 AppleScript 接口，不启动浏览器、不创建 profile、不读取
Cookie、localStorage、认证头或整页 HTML。登录、安全验证和验证码始终由用户在同一
标签页中手动处理。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from integrations.boss.security import (
    boss_job_url_matches_expected,
    is_allowed_boss_job_url,
    is_allowed_boss_search_url,
)

_BROWSER_TARGETS = {
    "msedge": ("Microsoft Edge", "Microsoft Edge"),
    "chrome": ("Google Chrome", "Google Chrome"),
}
_BROWSER_ALIASES = {
    "edge": "msedge",
    "microsoft-edge": "msedge",
    "microsoft edge": "msedge",
    "msedge": "msedge",
    "chrome": "chrome",
    "google-chrome": "chrome",
    "google chrome": "chrome",
}
_BOSS_TAB_NOT_FOUND = "__NO_BOSS_TAB__"
_BROWSER_NOT_RUNNING = "__BROWSER_NOT_RUNNING__"
_BROWSER_WITHOUT_WINDOWS = "__NO_BROWSER_WINDOWS__"
_PINNED_BOSS_TAB_NOT_FOUND = "__PINNED_BOSS_TAB_NOT_FOUND__"
_JOB_PATH_RE = re.compile(r"/job_detail/[A-Za-z0-9_-]+\.html")
_COMPANY_SIZE_RE = re.compile(
    r"(?:少于)?\d{1,6}(?:-\d{1,6})?人(?:以上|以下)?|\d+(?:\.\d+)?万人(?:以上|以下)?"
)


class BossExistingTabError(RuntimeError):
    """表示现有浏览器标签页桥接的可诊断失败，不携带页面正文或认证数据。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 409,
        request_may_have_run: bool = False,
    ) -> None:
        """保存稳定错误码、脱敏提示和外部动作是否可能已经执行。"""
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.request_may_have_run = request_may_have_run


@dataclass(frozen=True)
class BossBrowserTarget:
    """描述一个受支持、可通过 AppleScript 控制的本机浏览器渠道。"""

    channel: str
    app_name: str
    label: str


@dataclass(frozen=True)
class BossTabExecution:
    """保存一次固定标签页脚本执行结果；tab id 仅在后端进程内用于防止读错页。"""

    tab_id: str
    result: str


@dataclass(frozen=True)
class BossTabStatus:
    """返回现有 BOSS 标签页的有限状态，不暴露页面正文或浏览器凭据。"""

    success: bool
    browser_channel: str
    browser_label: str
    connected: bool
    current_url: str
    page_status: str
    ready_state: str
    visible_card_count: int
    message: str
    tab_id: str = ""

    def as_dict(self) -> dict[str, Any]:
        """转换为可直接交给 API 响应模型的公开字段字典。"""
        return {
            "success": self.success,
            "browser_channel": self.browser_channel,
            "browser_label": self.browser_label,
            "connected": self.connected,
            "current_url": self.current_url,
            "page_status": self.page_status,
            "ready_state": self.ready_state,
            "visible_card_count": self.visible_card_count,
            "message": self.message,
        }


def normalize_existing_tab_browser_channel(value: str | None) -> str:
    """规范化前端或环境变量提供的浏览器渠道，只允许 Edge 与 Chrome。"""
    raw = str(value or "").strip().lower()
    if not raw:
        raw = str(os.getenv("BOSS_BROWSER_CHANNEL", "msedge")).strip().lower() or "msedge"
    normalized = _BROWSER_ALIASES.get(raw)
    if normalized is None:
        raise BossExistingTabError(
            "unsupported_browser_channel",
            "当前标签页接管只支持 Microsoft Edge 或 Google Chrome。",
            status_code=400,
        )
    return normalized


def get_existing_tab_browser_target(value: str | None) -> BossBrowserTarget:
    """解析白名单浏览器应用名，禁止把请求值直接插入 AppleScript。"""
    channel = normalize_existing_tab_browser_channel(value)
    app_name, label = _BROWSER_TARGETS[channel]
    return BossBrowserTarget(channel=channel, app_name=app_name, label=label)


def normalize_company_size_text(value: object) -> str:
    """只保留 BOSS 公司标签中的人数规模，避免把行业和融资阶段误显示为人数。"""
    normalized = re.sub(r"\s+", " ", str(value or "")).strip()[:200]
    match = _COMPANY_SIZE_RE.search(normalized)
    return match.group(0)[:100] if match else ""


def _bounded_env_float(
    name: str,
    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    """读取有界浮点环境配置，非法值回退默认值。"""
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(value, maximum))


def boss_existing_tab_poll_interval_seconds() -> float:
    """返回岗位页最小检查间隔；硬下限为 5 秒，避免高频读取页面。"""
    return _bounded_env_float(
        "BOSS_CAPTURE_POLL_INTERVAL_SECONDS",
        5.0,
        minimum=5.0,
        maximum=30.0,
    )


def boss_existing_tab_action_delay_seconds() -> float:
    """返回搜索前的保守动作间隔，不做指纹伪装或验证码规避。"""
    return _bounded_env_float(
        "BOSS_CAPTURE_ACTION_DELAY_SECONDS",
        2.0,
        minimum=1.0,
        maximum=10.0,
    )


def boss_existing_tab_max_cards(requested: int = 20) -> int:
    """把单次 DOM 候选卡片读取量限制在 1 到 20。"""
    try:
        configured = int(os.getenv("BOSS_CAPTURE_MAX_CANDIDATE_CARDS", "20"))
    except (TypeError, ValueError):
        configured = 20
    return max(1, min(int(requested), configured, 20))


_PRESERVED_SEARCH_PARAMS = {
    "degree",
    "experience",
    "industry",
    "jobType",
    "salary",
    "scale",
    "stage",
}


def build_boss_search_url(
    *,
    current_url: str,
    query: str,
    city: str | None,
) -> str:
    """基于当前官方页构造搜索 URL，保留明确允许的筛选项并重置翻页状态。"""
    query_value = str(query or "").strip()[:200]
    if not query_value:
        raise BossExistingTabError(
            "invalid_search_query",
            "搜索关键词不能为空。",
            status_code=400,
        )
    city_value = str(city or "").strip()[:20]
    parsed_current = urlparse(current_url)
    current_params = parse_qs(parsed_current.query, keep_blank_values=False)
    if not city_value:
        city_value = str((current_params.get("city") or [""])[0]).strip()[:20]
    if city_value and not city_value.isdigit():
        raise BossExistingTabError(
            "invalid_city_code",
            "BOSS 城市必须填写数字城市代码，例如 101280600。",
            status_code=400,
        )

    params: dict[str, str] = {}
    for name in _PRESERVED_SEARCH_PARAMS:
        value = str((current_params.get(name) or [""])[0]).strip()[:100]
        if value:
            params[name] = value
    if city_value:
        params["city"] = city_value
    params["query"] = query_value
    target_url = urlunparse((
        "https",
        "www.zhipin.com",
        "/web/geek/jobs",
        "",
        urlencode(params),
        "",
    ))
    if not is_allowed_boss_search_url(target_url):
        raise BossExistingTabError(
            "invalid_search_url",
            "无法构造受允许的 BOSS 官方岗位搜索页。",
            status_code=400,
        )
    return target_url


def boss_search_url_matches_intent(actual_url: str, expected_url: str) -> bool:
    """确认采集页已经反映目标关键词；目标显式城市存在时也必须一致。"""
    if not is_allowed_boss_search_url(actual_url) or not is_allowed_boss_search_url(expected_url):
        return False
    actual_params = parse_qs(urlparse(actual_url).query, keep_blank_values=False)
    expected_params = parse_qs(urlparse(expected_url).query, keep_blank_values=False)
    if (actual_params.get("query") or [""])[0] != (expected_params.get("query") or [""])[0]:
        return False
    expected_city = (expected_params.get("city") or [""])[0]
    return not expected_city or (actual_params.get("city") or [""])[0] == expected_city


def _select_existing_boss_tab_script(app_name: str, action_body: str) -> str:
    """构造锁定既有 BOSS 标签页的 JXA；应用名固定，tab id 通过 argv 参数传入。"""
    return f"""
function isBossURL(value) {{
  const url = String(value || '');
  return url.startsWith('https://www.zhipin.com/') || url.startsWith('https://zhipin.com/');
}}

function safeTabID(tab) {{
  try {{ return String(tab.id() || ''); }} catch (_) {{ return ''; }}
}}

function run(argv) {{
  const expectedTabID = String(argv[0] || '');
  const browser = Application({json.dumps(app_name)});
  if (!browser.running()) return {json.dumps(_BROWSER_NOT_RUNNING)};
  const windows = browser.windows();
  if (!windows.length) return {json.dumps(_BROWSER_WITHOUT_WINDOWS)};

  let selectedWindow = null;
  let selectedTab = null;
  let selectedTabIndex = -1;
  if (expectedTabID) {{
    for (const candidateWindow of windows) {{
      const tabs = candidateWindow.tabs();
      for (let index = 0; index < tabs.length; index += 1) {{
        if (safeTabID(tabs[index]) !== expectedTabID) continue;
        let candidateURL = '';
        try {{ candidateURL = tabs[index].url(); }} catch (_) {{}}
        if (!isBossURL(candidateURL)) return {json.dumps(_PINNED_BOSS_TAB_NOT_FOUND)};
        selectedWindow = candidateWindow;
        selectedTab = tabs[index];
        selectedTabIndex = index;
        break;
      }}
      if (selectedTab) break;
    }}
    if (!selectedTab) return {json.dumps(_PINNED_BOSS_TAB_NOT_FOUND)};
  }} else {{
    try {{
      const activeTab = windows[0].activeTab();
      if (isBossURL(activeTab.url())) {{
        selectedWindow = windows[0];
        selectedTab = activeTab;
        selectedTabIndex = Number(windows[0].activeTabIndex()) - 1;
      }}
    }} catch (_) {{}}

    if (!selectedTab) {{
      for (const candidateWindow of windows) {{
        const tabs = candidateWindow.tabs();
        for (let index = 0; index < tabs.length; index += 1) {{
          let candidateURL = '';
          try {{ candidateURL = tabs[index].url(); }} catch (_) {{ continue; }}
          if (!isBossURL(candidateURL)) continue;
          selectedWindow = candidateWindow;
          selectedTab = tabs[index];
          selectedTabIndex = index;
          break;
        }}
        if (selectedTab) break;
      }}
    }}
  }}

  if (!selectedTab) return {json.dumps(_BOSS_TAB_NOT_FOUND)};
  {action_body}
}}
""".strip()


_STATUS_JAVASCRIPT = r"""
(() => {
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const url = location.href;
  const path = location.pathname.replace(/\/+$/, '').toLowerCase();
  const text = clean(document.body ? document.body.innerText : '').slice(0, 6000);
  const loginMarkers = ['扫码登录', '手机号登录', '密码登录', '登录/注册', '登录后继续'];
  const securityMarkers = ['安全验证', '请完成验证', '访问异常', '行为验证', '拖动滑块'];
  let visibleCardCount = 0;
  const seen = new Set();
  for (const link of document.querySelectorAll('a[href*="/job_detail/"]')) {
    if (visibleCardCount >= 20) break;
    let parsed;
    try { parsed = new URL(link.href, location.href); } catch { continue; }
    if (!/^\/job_detail\/[A-Za-z0-9_-]+\.html$/.test(parsed.pathname)) continue;
    if (seen.has(parsed.pathname) || link.getClientRects().length === 0) continue;
    seen.add(parsed.pathname);
    visibleCardCount += 1;
  }
  let pageStatus = 'boss_page';
  if (url === 'about:blank' || !url) pageStatus = 'blank';
  else if (path === '/web/user' || loginMarkers.some(marker => text.includes(marker))) pageStatus = 'login_required';
  else if (path.includes('security') || path.includes('verify') || securityMarkers.some(marker => text.includes(marker))) pageStatus = 'security_check';
  else if (path === '/web/geek/job' || path === '/web/geek/jobs') {
    pageStatus = visibleCardCount > 0 ? 'search_ready' : 'search_loading';
  }
  return JSON.stringify({
    current_url: url,
    page_status: pageStatus,
    ready_state: document.readyState || '',
    visible_card_count: Math.min(visibleCardCount, 20),
  });
})()
""".strip()


_CAPTURE_JAVASCRIPT = r"""
(() => {
  const MAX_CARDS = 20;
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const pick = (root, selectors) => {
    for (const selector of selectors) {
      const element = root.querySelector(selector);
      const value = clean(element ? (element.innerText || element.textContent) : '');
      if (value) return value;
    }
    return '';
  };
  const url = location.href;
  const path = location.pathname.replace(/\/+$/, '').toLowerCase();
  const pageText = clean(document.body ? document.body.innerText : '').slice(0, 6000);
  const loginMarkers = ['扫码登录', '手机号登录', '密码登录', '登录/注册', '登录后继续'];
  const securityMarkers = ['安全验证', '请完成验证', '访问异常', '行为验证', '拖动滑块'];
  let pageStatus = 'boss_page';
  if (path === '/web/user' || loginMarkers.some(marker => pageText.includes(marker))) pageStatus = 'login_required';
  else if (path.includes('security') || path.includes('verify') || securityMarkers.some(marker => pageText.includes(marker))) pageStatus = 'security_check';
  else if (path === '/web/geek/job' || path === '/web/geek/jobs') pageStatus = 'search_loading';

  const cards = [];
  const seen = new Set();
  for (const link of document.querySelectorAll('a[href*="/job_detail/"]')) {
    if (cards.length >= MAX_CARDS) break;
    if (link.getClientRects().length === 0) continue;
    let parsed;
    try { parsed = new URL(link.href, location.href); } catch { continue; }
    const hostname = parsed.hostname.toLowerCase();
    if (parsed.protocol !== 'https:') continue;
    if (!(hostname === 'zhipin.com' || hostname.endsWith('.zhipin.com'))) continue;
    if (!/^\/job_detail\/[A-Za-z0-9_-]+\.html$/.test(parsed.pathname)) continue;
    if (seen.has(parsed.pathname)) continue;

    const root = link.closest('.job-card-wrapper,.job-card-box,li[class*="job-card"],[class*="job-card-wrapper"]');
    if (!root) continue;
    const jobTitle = pick(root, ['.job-name', '[class*="job-name"]', '[class*="job-title"]'])
      || clean(link.innerText || link.textContent).split(' ')[0];
    const companyName = pick(root, ['.company-name', '[class*="company-name"]', '[class*="company-title"]']);
    const salaryText = pick(root, ['.job-salary', '.salary', '[class*="job-salary"]', '[class*="salary"]']);
    const city = pick(root, ['.job-area', '[class*="job-area"]', '[class*="job-location"]']);
    const titleSummary = pick(root, ['.tag-list', '[class*="tag-list"]', '[class*="job-info"]']).slice(0, 300);
    const companyMetaText = pick(root, ['.company-tag-list', '[class*="company-tag-list"]', '[class*="company-info"]', '[class*="company-scale"]']).slice(0, 200);
    const companySizeMatch = companyMetaText.match(/(?:少于)?\d{1,6}(?:-\d{1,6})?人(?:以上|以下)?|\d+(?:\.\d+)?万人(?:以上|以下)?/);
    const companySizeText = companySizeMatch ? companySizeMatch[0] : '';
    const jobDescription = clean(root.innerText || root.textContent).slice(0, 3000);
    const internshipText = `${jobTitle} ${titleSummary} ${jobDescription}`.toLowerCase();
    if (/(实习|实习生|internship|\\bintern\\b)/i.test(internshipText)) continue;
    if (!jobTitle || jobDescription.length < 8 || (!companyName && !salaryText)) continue;

    seen.add(parsed.pathname);
    cards.push({
      company_name: companyName.slice(0, 200),
      company_size_text: companySizeText,
      job_title: jobTitle.slice(0, 200),
      salary_text: salaryText.slice(0, 100),
      city: city.slice(0, 100),
      title_summary: titleSummary,
      job_description: jobDescription,
      source_url: parsed.href,
    });
  }
  if ((path === '/web/geek/job' || path === '/web/geek/jobs') && cards.length > 0) pageStatus = 'search_ready';
  return JSON.stringify({
    kind: 'interviewmind-boss-dom-capture-v1',
    source_page_url: url,
    captured_at: new Date().toISOString(),
    page_status: pageStatus,
    ready_state: document.readyState || '',
    cards,
  });
})()
""".strip()


_OPEN_CONTACT_JAVASCRIPT = r"""
(() => {
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const visible = (element) => Boolean(element && element.getClientRects().length && !element.disabled);
  const pageText = clean(document.body ? document.body.innerText : '').slice(0, 6000);
  if (['扫码登录', '手机号登录', '密码登录', '登录后继续'].some(marker => pageText.includes(marker))) {
    return JSON.stringify({status: 'login_required'});
  }
  if (['安全验证', '请完成验证', '访问异常', '行为验证', '拖动滑块'].some(marker => pageText.includes(marker))) {
    return JSON.stringify({status: 'security_check'});
  }
  const composerSelectors = [
    'textarea',
    '[contenteditable="true"]',
    '[class*="chat-input"]',
    '[class*="message-input"]',
  ];
  const composer = composerSelectors
    .flatMap(selector => Array.from(document.querySelectorAll(selector)))
    .find(visible);
  if (composer) return JSON.stringify({status: 'composer_ready'});

  const allowedLabels = ['立即沟通', '继续沟通', '打招呼', '沟通'];
  const contact = Array.from(document.querySelectorAll('button, a, [role="button"]'))
    .find(element => {
      if (!visible(element)) return false;
      const label = clean(element.innerText || element.textContent || element.getAttribute('aria-label'));
      return label.length <= 12 && allowedLabels.includes(label);
    });
  if (!contact) return JSON.stringify({status: 'contact_action_not_found'});
  contact.click();
  return JSON.stringify({status: 'contact_clicked'});
})()
""".strip()


def _build_send_message_javascript(message_text: str) -> str:
    """构造只向可见聊天编辑器写入有界文案并点击一次发送的固定脚本。"""

    message = json.dumps(message_text)
    return r"""
(() => {
  const message = MESSAGE_VALUE;
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const visible = (element) => Boolean(element && element.getClientRects().length && !element.disabled);
  const composerSelectors = [
    'textarea',
    '[contenteditable="true"]',
    '[class*="chat-input"]',
    '[class*="message-input"]',
  ];
  const composer = composerSelectors
    .flatMap(selector => Array.from(document.querySelectorAll(selector)))
    .find(visible);
  if (!composer) return JSON.stringify({status: 'message_composer_not_found'});

  composer.focus();
  if (composer instanceof HTMLTextAreaElement || composer instanceof HTMLInputElement) {
    const prototype = composer instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(prototype, 'value').set;
    setter.call(composer, message);
  } else {
    composer.textContent = message;
  }
  composer.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: message}));
  composer.dispatchEvent(new Event('change', {bubbles: true}));

  const send = Array.from(document.querySelectorAll('button, [role="button"], [class*="send"]'))
    .find(element => {
      if (!visible(element)) return false;
      const label = clean(
        element.innerText || element.textContent || element.getAttribute('aria-label') || element.title
      );
      return label === '发送' || label === '发送消息';
    });
  if (!send) return JSON.stringify({status: 'send_button_not_found'});
  send.click();
  return JSON.stringify({status: 'send_clicked'});
})()
""".replace('MESSAGE_VALUE', message).strip()


def _build_verify_message_javascript(message_text: str) -> str:
    """构造发送后置条件检查，只判断可见消息气泡，不读取或返回聊天正文。"""

    message = json.dumps(message_text)
    return r"""
(() => {
  const message = MESSAGE_VALUE;
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const expected = clean(message);
  const candidates = Array.from(document.querySelectorAll(
    '[class*="message"], [class*="bubble"], [class*="chat-record"], li, p'
  ));
  const matched = candidates.some(element => {
    if (!element.getClientRects().length || element.closest('[contenteditable="true"]')) return false;
    return clean(element.innerText || element.textContent) === expected;
  });
  return JSON.stringify({status: matched ? 'sent' : 'unverified'});
})()
""".replace('MESSAGE_VALUE', message).strip()



class BossExistingTabBridge:
    """通过浏览器官方 AppleScript 接口接管既有 BOSS 标签页并限速采集。"""

    def __init__(self) -> None:
        """初始化进程内渠道锁和状态缓存，避免并发脚本操作同一标签页。"""
        self._locks = {channel: asyncio.Lock() for channel in _BROWSER_TARGETS}
        self._status_cache: dict[str, tuple[float, BossTabStatus]] = {}
        self._last_action_at: dict[str, float] = {}

    def _fresh_cached_status(self, target: BossBrowserTarget) -> BossTabStatus | None:
        """返回五秒窗口内的同渠道状态，避免连接后立即再次读取同一页面 DOM。"""
        cached = self._status_cache.get(target.channel)
        if cached and monotonic() - cached[0] < boss_existing_tab_poll_interval_seconds():
            return cached[1]
        return None

    async def _run_applescript(
        self,
        script: str,
        *arguments: str,
        timeout_seconds: float = 10.0,
        timeout_context: str = "",
    ) -> str:
        """参数化执行 osascript；超时或权限失败时只返回脱敏诊断。"""
        if sys.platform != "darwin":
            raise BossExistingTabError(
                "unsupported_platform",
                "复用现有浏览器标签页仅支持运行在 macOS 宿主机上的后端。",
            )
        try:
            process = await asyncio.create_subprocess_exec(
                "/usr/bin/osascript",
                "-l",
                "JavaScript",
                "-e",
                script,
                "--",
                *arguments,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise BossExistingTabError(
                "osascript_unavailable",
                "无法调用 macOS AppleScript，请确认后端运行在本机而不是容器中。",
            ) from exc
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout_seconds,
            )
        except TimeoutError as exc:
            process.kill()
            await process.communicate()
            base_message = (
                "浏览器接管请求超时。请确认正在运行 browser_automation_service 的那个宿主机 App "
                "已被授权控制浏览器：如果服务由 Terminal/iTerm 启动，就授权 Terminal/iTerm；"
                "如果由 PyCharm 启动，才授权 PyCharm。即使 PyCharm 下已勾选 Edge，"
                "若当前服务是用终端脚本启动，仍需要给启动终端授权。同时请确认 Edge/Chrome "
                "已开启“查看 → 开发人员 → 允许 Apple 事件中的 JavaScript”。"
            )
            if timeout_context:
                base_message = f"{base_message} 当前卡住阶段：{timeout_context}。"
            raise BossExistingTabError(
                "browser_automation_permission_timeout",
                base_message,
            ) from exc

        if process.returncode != 0:
            error_text = stderr.decode("utf-8", errors="replace").lower()
            if "-1743" in error_text or "not authorized" in error_text or "不被允许" in error_text:
                message = "macOS 尚未授权后端控制浏览器，请在“隐私与安全性 → 自动化”中开启权限。"
                code = "browser_automation_permission_denied"
            elif "javascript" in error_text and ("apple event" in error_text or "apple events" in error_text):
                message = "请在浏览器“查看 → 开发人员”中开启“允许 Apple 事件中的 JavaScript”。"
                code = "browser_javascript_disabled"
            else:
                message = "无法读取当前浏览器标签页。请确认浏览器正在运行且 Apple 事件 JavaScript 已开启。"
                code = "browser_control_failed"
            raise BossExistingTabError(code, message)
        return stdout.decode("utf-8", errors="replace").strip()

    @staticmethod
    def _parse_execution_envelope(result: str) -> BossTabExecution:
        """解析 JXA 最小执行信封，拒绝缺少固定 tab id 的浏览器结果。"""
        try:
            payload = json.loads(result)
        except json.JSONDecodeError as exc:
            raise BossExistingTabError(
                "invalid_browser_response",
                "浏览器返回了无法识别的标签页执行结果。",
            ) from exc
        if not isinstance(payload, dict):
            raise BossExistingTabError(
                "invalid_browser_response",
                "浏览器标签页执行结果格式无效。",
            )
        tab_id = str(payload.get("tab_id") or "").strip()[:200]
        if not tab_id:
            raise BossExistingTabError(
                "invalid_browser_response",
                "浏览器没有返回可锁定的 BOSS 标签页标识。",
            )
        return BossTabExecution(
            tab_id=tab_id,
            result=str(payload.get("result") or ""),
        )

    async def _execute_in_existing_tab(
        self,
        target: BossBrowserTarget,
        javascript: str,
        *,
        expected_tab_id: str = "",
    ) -> BossTabExecution:
        """在同一既有 BOSS 标签页执行固定 JavaScript，不创建、关闭或反复激活标签页。"""
        script = _select_existing_boss_tab_script(
            target.app_name,
            "const javascriptSource = argv[1];\n"
            "  const pageResult = browser.execute(selectedTab, {javascript: javascriptSource});\n"
            "  return JSON.stringify({tab_id: safeTabID(selectedTab), result: String(pageResult || '')});",
        )
        result = await self._run_applescript(
            script,
            expected_tab_id,
            javascript,
            timeout_seconds=20.0,
            timeout_context="已找到浏览器标签页后执行页面 JavaScript",
        )
        self._raise_for_marker(result, target)
        return self._parse_execution_envelope(result)

    async def _navigate_existing_tab(
        self,
        target: BossBrowserTarget,
        target_url: str,
        *,
        expected_tab_id: str,
        allow_job_detail: bool = False,
    ) -> str:
        """只导航已锁定的 BOSS 标签页并激活一次，后续轮询不再抢占用户焦点。"""
        allowed = is_allowed_boss_search_url(target_url) or (allow_job_detail and is_allowed_boss_job_url(target_url))
        if not allowed:
            raise BossExistingTabError(
                "invalid_search_url",
                "只允许把现有标签页导航到 BOSS 官方搜索页或已保存岗位详情页。",
                status_code=400,
            )
        script = _select_existing_boss_tab_script(
            target.app_name,
            "const targetURL = argv[1];\n"
            "  selectedTab.url = targetURL;\n"
            "  selectedWindow.activeTabIndex = selectedTabIndex + 1;\n"
            "  return JSON.stringify({tab_id: safeTabID(selectedTab), result: targetURL});",
        )
        result = await self._run_applescript(
            script,
            expected_tab_id,
            target_url,
            timeout_seconds=20.0,
            timeout_context="导航并激活已锁定的 BOSS 标签页",
        )
        self._raise_for_marker(result, target)
        return self._parse_execution_envelope(result).tab_id

    @staticmethod
    def _raise_for_marker(result: str, target: BossBrowserTarget) -> None:
        """把 AppleScript 稳定标记转换为用户可操作的桥接错误。"""
        if result == _BROWSER_NOT_RUNNING:
            raise BossExistingTabError(
                "browser_not_running",
                f"{target.label} 未运行；请先打开你已经登录的 BOSS 页面。",
                status_code=409,
            )
        if result == _BROWSER_WITHOUT_WINDOWS:
            raise BossExistingTabError(
                "browser_has_no_windows",
                f"{target.label} 没有可用窗口；程序不会替你新建浏览器窗口。",
                status_code=409,
            )
        if result == _BOSS_TAB_NOT_FOUND:
            raise BossExistingTabError(
                "boss_tab_not_found",
                f"未在 {target.label} 中找到已打开的 BOSS 标签页，请先打开并停留在 BOSS 页面。",
                status_code=409,
            )
        if result == _PINNED_BOSS_TAB_NOT_FOUND:
            raise BossExistingTabError(
                "boss_tab_changed",
                "已连接的 BOSS 标签页已关闭或离开官方页面；为避免读错标签页，本次采集已停止。",
                status_code=409,
            )

    @staticmethod
    def _status_from_payload(target: BossBrowserTarget, payload: dict[str, Any]) -> BossTabStatus:
        """把页面脚本返回值收敛为有限公开状态。"""
        current_url = str(payload.get("current_url") or "")[:2048]
        page_status = str(payload.get("page_status") or "boss_page")[:50]
        ready_state = str(payload.get("ready_state") or "")[:30]
        try:
            visible_card_count = max(0, min(int(payload.get("visible_card_count", 0)), 20))
        except (TypeError, ValueError):
            visible_card_count = 0
        messages = {
            "search_ready": f"已连接 {target.label} 当前 BOSS 搜索页，可读取 {visible_card_count} 张岗位卡片。",
            "search_loading": "已连接 BOSS 搜索页，岗位列表仍在加载。",
            "login_required": "当前标签页需要登录，请在同一标签页手动完成登录后重试。",
            "security_check": "当前标签页需要安全验证，请手动完成后重试；程序不会绕过验证。",
            "blank": "当前标签页为空白页，请手动恢复 BOSS 页面后重试。",
            "boss_page": "已找到 BOSS 标签页，请进入岗位搜索结果页后重试。",
        }
        return BossTabStatus(
            success=True,
            browser_channel=target.channel,
            browser_label=target.label,
            connected=True,
            current_url=current_url,
            page_status=page_status,
            ready_state=ready_state,
            visible_card_count=visible_card_count,
            message=messages.get(page_status, "已连接现有 BOSS 标签页。"),
        )

    @staticmethod
    def _action_status(execution: BossTabExecution) -> str:
        """解析页面动作的最小状态，不接受或向上返回页面正文。"""

        try:
            payload = json.loads(execution.result)
        except json.JSONDecodeError as exc:
            raise BossExistingTabError(
                "invalid_browser_response",
                "浏览器返回了无法识别的页面动作状态。",
            ) from exc
        if not isinstance(payload, dict):
            raise BossExistingTabError(
                "invalid_browser_response",
                "浏览器页面动作状态格式无效。",
            )
        return str(payload.get("status") or "")[:80]

    async def _inspect_unlocked(
        self,
        target: BossBrowserTarget,
        *,
        expected_tab_id: str = "",
    ) -> BossTabStatus:
        """读取一次有限页面状态并保留内部 tab id；调用方负责渠道锁和五秒缓存。"""
        execution = await self._execute_in_existing_tab(
            target,
            _STATUS_JAVASCRIPT,
            expected_tab_id=expected_tab_id,
        )
        try:
            payload = json.loads(execution.result)
        except json.JSONDecodeError as exc:
            raise BossExistingTabError(
                "invalid_browser_response",
                "浏览器返回了无法识别的页面状态，请确认 Apple 事件 JavaScript 已开启。",
            ) from exc
        if not isinstance(payload, dict):
            raise BossExistingTabError(
                "invalid_browser_response",
                "浏览器页面状态格式无效。",
            )
        status = BossTabStatus(
            **self._status_from_payload(target, payload).as_dict(),
            tab_id=execution.tab_id,
        )
        self._status_cache[target.channel] = (monotonic(), status)
        return status

    async def inspect(self, browser_channel: str | None = None) -> BossTabStatus:
        """连接并检查当前 BOSS 标签页；五秒内重复请求复用缓存而不重复读 DOM。"""
        target = get_existing_tab_browser_target(browser_channel)
        async with self._locks[target.channel]:
            cached = self._fresh_cached_status(target)
            if cached is not None:
                return cached
            return await self._inspect_unlocked(target)

    async def _respect_action_spacing(self, target: BossBrowserTarget) -> None:
        """确保同一浏览器渠道的导航动作之间保留保守间隔。"""
        last_action = self._last_action_at.get(target.channel)
        delay = boss_existing_tab_action_delay_seconds()
        if last_action is not None:
            remaining = delay - (monotonic() - last_action)
            if remaining > 0:
                await asyncio.sleep(remaining)
        else:
            await asyncio.sleep(delay)

    async def _capture_unlocked(
        self,
        target: BossBrowserTarget,
        *,
        max_cards: int,
        expected_tab_id: str = "",
    ) -> dict[str, Any]:
        """在已锁定标签页读取最多 20 张候选卡片，并再次做 URL 与字段过滤。"""
        execution = await self._execute_in_existing_tab(
            target,
            _CAPTURE_JAVASCRIPT,
            expected_tab_id=expected_tab_id,
        )
        try:
            payload = json.loads(execution.result)
        except json.JSONDecodeError as exc:
            raise BossExistingTabError(
                "invalid_browser_response",
                "浏览器返回的岗位数据格式无效。",
            ) from exc
        if not isinstance(payload, dict):
            raise BossExistingTabError("invalid_browser_response", "浏览器返回的岗位数据格式无效。")

        source_page_url = str(payload.get("source_page_url") or "")[:2048]
        page_status = str(payload.get("page_status") or "boss_page")[:50]
        ready_state = str(payload.get("ready_state") or "")[:30]
        raw_cards = payload.get("cards") if isinstance(payload.get("cards"), list) else []
        cards: list[dict[str, str]] = []
        for raw_card in raw_cards[:boss_existing_tab_max_cards(max_cards)]:
            if not isinstance(raw_card, dict):
                continue
            card = {
                "company_name": str(raw_card.get("company_name") or "").strip()[:200],
                "company_size_text": normalize_company_size_text(raw_card.get("company_size_text")),
                "job_title": str(raw_card.get("job_title") or "").strip()[:200],
                "salary_text": str(raw_card.get("salary_text") or "").strip()[:100],
                "city": str(raw_card.get("city") or "").strip()[:100],
                "title_summary": str(raw_card.get("title_summary") or "").strip()[:300],
                "job_description": str(raw_card.get("job_description") or "").strip()[:3000],
                "source_url": str(raw_card.get("source_url") or "").strip()[:2048],
            }
            internship_text = " ".join(
                (card["job_title"], card["title_summary"], card["job_description"])
            ).lower()
            if re.search(r"实习|实习生|internship|\bintern\b", internship_text, re.IGNORECASE):
                continue
            if not card["job_title"] or len(card["job_description"]) < 8:
                continue
            if not (card["company_name"] or card["salary_text"]):
                continue
            if not is_allowed_boss_job_url(card["source_url"]):
                continue
            if _JOB_PATH_RE.fullmatch(urlparse(card["source_url"]).path) is None:
                continue
            cards.append(card)

        return {
            "kind": "interviewmind-boss-dom-capture-v1",
            "tab_id": execution.tab_id,
            "source_page_url": source_page_url,
            "captured_at": str(payload.get("captured_at") or datetime.now(timezone.utc).isoformat()),
            "page_status": page_status,
            "ready_state": ready_state,
            "cards": cards,
        }

    async def search_and_capture(
        self,
        *,
        query: str,
        city: str | None = None,
        max_cards: int = 20,
        browser_channel: str | None = None,
        max_checks: int = 6,
    ) -> dict[str, Any]:
        """在现有 BOSS 标签页搜索并按至少五秒间隔检查，返回最多 20 张卡片。"""
        target = get_existing_tab_browser_target(browser_channel)
        card_limit = boss_existing_tab_max_cards(max_cards)
        async with self._locks[target.channel]:
            initial_status = self._fresh_cached_status(target)
            if initial_status is None:
                initial_status = await self._inspect_unlocked(target)
            if initial_status.page_status == "login_required":
                raise BossExistingTabError(
                    "login_required",
                    "当前 BOSS 标签页尚未登录，请在同一标签页手动完成登录后重试。",
                    status_code=409,
                )
            if initial_status.page_status == "security_check":
                raise BossExistingTabError(
                    "security_check_required",
                    "当前 BOSS 标签页需要安全验证，请手动完成后再采集；程序不会绕过验证。",
                    status_code=409,
                )
            await self._respect_action_spacing(target)
            target_url = build_boss_search_url(
                current_url=initial_status.current_url,
                query=query,
                city=city,
            )
            pinned_tab_id = await self._navigate_existing_tab(
                target,
                target_url,
                expected_tab_id=initial_status.tab_id,
            )
            self._last_action_at[target.channel] = monotonic()
            self._status_cache.pop(target.channel, None)

            checks = max(1, min(int(max_checks), 12))
            for _ in range(checks):
                await asyncio.sleep(boss_existing_tab_poll_interval_seconds())
                capture = await self._capture_unlocked(
                    target,
                    max_cards=card_limit,
                    expected_tab_id=pinned_tab_id,
                )
                page_status = capture["page_status"]
                if page_status == "login_required":
                    raise BossExistingTabError(
                        "login_required",
                        "现有浏览器登录态已失效，请在同一标签页手动登录后重试。",
                        status_code=409,
                    )
                if page_status == "security_check":
                    raise BossExistingTabError(
                        "security_check_required",
                        "BOSS 要求安全验证，请在同一标签页手动完成后重试；程序不会绕过验证。",
                        status_code=409,
                    )
                if (
                    page_status == "search_ready"
                    and boss_search_url_matches_intent(capture["source_page_url"], target_url)
                    and capture["cards"]
                ):
                    self._status_cache[target.channel] = (
                        monotonic(),
                        BossTabStatus(
                            success=True,
                            browser_channel=target.channel,
                            browser_label=target.label,
                            connected=True,
                            current_url=capture["source_page_url"],
                            page_status=page_status,
                            ready_state=capture["ready_state"],
                            visible_card_count=len(capture["cards"]),
                            message=f"已从现有 {target.label} 标签页读取 {len(capture['cards'])} 张岗位卡片。",
                            tab_id=pinned_tab_id,
                        ),
                    )
                    capture.pop("tab_id", None)
                    return {
                        "success": True,
                        "browser_channel": target.channel,
                        "browser_label": target.label,
                        "message": f"已复用现有 {target.label} 登录页完成搜索和有限字段采集。",
                        **capture,
                    }

            raise BossExistingTabError(
                "job_cards_timeout",
                "岗位列表在保守等待时间内仍未出现。请检查当前标签页是否加载完成或需要手动验证。",
                status_code=409,
            )


    async def send_message(
        self,
        *,
        source_url: str,
        message_text: str,
        browser_channel: str | None = None,
    ) -> dict[str, Any]:
        """在锁定的 BOSS 标签页发送一次文案，并要求消息气泡后置条件成立。"""

        message = str(message_text or "").strip()
        if not is_allowed_boss_job_url(source_url):
            raise BossExistingTabError(
                "invalid_job_url",
                "只允许向已保存的 BOSS 官方岗位发送沟通文案。",
                status_code=400,
            )
        if not 20 <= len(message) <= 500 or any(ord(char) < 32 and char not in "\n\t" for char in message):
            raise BossExistingTabError(
                "invalid_message",
                "沟通文案长度必须为 20-500 字且不能包含控制字符。",
                status_code=400,
            )

        target = get_existing_tab_browser_target(browser_channel)
        async with self._locks[target.channel]:
            status = await self._inspect_unlocked(target)
            if status.page_status == "login_required":
                raise BossExistingTabError(
                    "login_required",
                    "当前 BOSS 标签页尚未登录，请手动登录后重试。",
                )
            if status.page_status == "security_check":
                raise BossExistingTabError(
                    "security_check_required",
                    "当前 BOSS 标签页需要安全验证，请手动完成后重试。",
                )

            await self._respect_action_spacing(target)
            tab_id = await self._navigate_existing_tab(
                target,
                source_url,
                expected_tab_id=status.tab_id,
                allow_job_detail=True,
            )
            await asyncio.sleep(boss_existing_tab_poll_interval_seconds())
            navigated_status = await self._inspect_unlocked(
                target,
                expected_tab_id=tab_id,
            )
            if not boss_job_url_matches_expected(
                navigated_status.current_url,
                source_url,
            ):
                raise BossExistingTabError(
                    "job_navigation_mismatch",
                    "岗位导航结果与已保存链接不一致，本次发送已安全停止。",
                )

            contact_status = self._action_status(await self._execute_in_existing_tab(
                target,
                _OPEN_CONTACT_JAVASCRIPT,
                expected_tab_id=tab_id,
            ))
            if contact_status == "contact_clicked":
                await asyncio.sleep(boss_existing_tab_action_delay_seconds())
                contact_status = self._action_status(await self._execute_in_existing_tab(
                    target,
                    _OPEN_CONTACT_JAVASCRIPT,
                    expected_tab_id=tab_id,
                ))
            if contact_status == "login_required":
                raise BossExistingTabError("login_required", "BOSS 登录态已失效，请手动登录后重试。")
            if contact_status == "security_check":
                raise BossExistingTabError(
                    "security_check_required",
                    "BOSS 要求安全验证，请手动完成后重试。",
                )
            if contact_status != "composer_ready":
                raise BossExistingTabError(
                    "contact_action_unavailable",
                    "未找到可用的 BOSS 沟通入口或消息编辑器，请在页面中手动确认岗位状态。",
                )

            try:
                send_status = self._action_status(await self._execute_in_existing_tab(
                    target,
                    _build_send_message_javascript(message),
                    expected_tab_id=tab_id,
                ))
            except BossExistingTabError as exc:
                raise BossExistingTabError(
                    exc.code,
                    exc.message,
                    status_code=exc.status_code,
                    request_may_have_run=True,
                ) from exc
            if send_status != "send_clicked":
                raise BossExistingTabError(
                    "message_send_unavailable",
                    "未找到可用的消息编辑器或发送按钮，本次没有确认执行发送。",
                )

            self._last_action_at[target.channel] = monotonic()
            self._status_cache.pop(target.channel, None)
            await asyncio.sleep(boss_existing_tab_poll_interval_seconds())
            try:
                verified = self._action_status(await self._execute_in_existing_tab(
                    target,
                    _build_verify_message_javascript(message),
                    expected_tab_id=tab_id,
                ))
            except BossExistingTabError as exc:
                raise BossExistingTabError(
                    exc.code,
                    exc.message,
                    status_code=exc.status_code,
                    request_may_have_run=True,
                ) from exc
            if verified != "sent":
                raise BossExistingTabError(
                    "message_send_unverified",
                    "已点击发送但未观察到消息气泡，请人工检查后再决定是否重试。",
                    request_may_have_run=True,
                )
            return {
                "success": True,
                "status": "sent",
                "browser_channel": target.channel,
                "browser_label": target.label,
                "message": "BOSS 沟通文案已发送并通过页面后置条件确认。",
            }


    async def open_job(
        self,
        source_url: str,
        browser_channel: str | None = None,
    ) -> dict[str, Any]:
        """把既有登录 BOSS 标签页导航到已持久化的官方岗位详情页。"""
        if not is_allowed_boss_job_url(source_url):
            raise BossExistingTabError(
                "invalid_job_url",
                "只允许在现有标签页打开已保存的 BOSS 官方岗位详情链接。",
                status_code=400,
            )
        target = get_existing_tab_browser_target(browser_channel)
        async with self._locks[target.channel]:
            status = await self._inspect_unlocked(target)
            tab_id = await self._navigate_existing_tab(
                target,
                source_url,
                expected_tab_id=status.tab_id,
                allow_job_detail=True,
            )
            self._last_action_at[target.channel] = monotonic()
            self._status_cache.pop(target.channel, None)
            await asyncio.sleep(boss_existing_tab_poll_interval_seconds())
            navigated_status = await self._inspect_unlocked(
                target,
                expected_tab_id=tab_id,
            )
            if not boss_job_url_matches_expected(
                navigated_status.current_url,
                source_url,
            ):
                raise BossExistingTabError(
                    "job_navigation_mismatch",
                    "岗位导航结果与已保存链接不一致，本次打开已安全停止。",
                )
            return {
                "success": True,
                "browser_channel": target.channel,
                "browser_label": target.label,
                "opened_url": source_url,
                "message": f"已在现有 {target.label} BOSS 标签页打开岗位详情。",
                "tab_locked": bool(tab_id),
            }


_boss_existing_tab_bridge = BossExistingTabBridge()


def get_boss_existing_tab_bridge() -> BossExistingTabBridge:
    """返回进程内共享桥接实例，以复用锁、动作间隔和五秒状态缓存。"""
    return _boss_existing_tab_bridge
