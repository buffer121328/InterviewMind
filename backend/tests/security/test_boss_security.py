"""BOSS URL 白名单与导航后置条件回归测试。"""

import pytest

from integrations.boss.security import (
    boss_job_url_matches_expected,
    is_allowed_boss_job_url,
    is_allowed_boss_origin_url,
    is_allowed_boss_search_url,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.zhipin.com/job_detail/abc_DEF-123.html",
        "https://zhipin.com/job_detail/abc123.html?ka=search_list_jname_1_blank",
        "https://m.zhipin.com/job_detail/abc123.html#detail",
    ],
)
def test_allowed_boss_job_urls_use_official_https_origin(url):
    """正常官方岗位 URL 可通过白名单。"""
    assert is_allowed_boss_job_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "http://www.zhipin.com/job_detail/abc123.html",
        "https://www.zhipin.com:444/job_detail/abc123.html",
        "https://user:password@www.zhipin.com/job_detail/abc123.html",
        "https://www.zhipin.com.evil.example/job_detail/abc123.html",
        "https://www.zhipin.com%2e.evil.example/job_detail/abc123.html",
        "https://evil.example/?next=https://www.zhipin.com/job_detail/abc123.html",
        "https://www.zhipin.com/web/geek/jobs",
        "https://www.zhipin.com/job_detail/%2e%2e%2fweb%2fgeek%2fjobs.html",
        "https://www.zhipin.com/job_detail/abc123.html.evil",
        "https://[invalid/job_detail/abc123.html",
    ],
)
def test_boss_job_url_rejects_origin_and_encoding_bypasses(url):
    """用户信息、端口、伪子域和编码路径不能绕过岗位白名单。"""
    assert is_allowed_boss_job_url(url) is False


def test_boss_search_url_requires_exact_search_path():
    """搜索页只接受固定路径，岗位和相似前缀路径均拒绝。"""
    assert is_allowed_boss_search_url(
        "https://www.zhipin.com/web/geek/jobs?query=agent"
    ) is True
    assert is_allowed_boss_search_url(
        "https://www.zhipin.com/web/geek/jobs/redirect"
    ) is False
    assert is_allowed_boss_origin_url("https://www.zhipin.com:443/") is True


def test_navigation_must_remain_on_same_boss_job_after_redirect():
    """导航后即使仍在官方域名，也不能悄悄切换到另一个岗位。"""
    expected = "https://www.zhipin.com/job_detail/job-a.html?from=search"

    assert boss_job_url_matches_expected(
        "https://m.zhipin.com/job_detail/job-a.html?from=redirect",
        expected,
    ) is True
    assert boss_job_url_matches_expected(
        "https://www.zhipin.com/job_detail/job-b.html",
        expected,
    ) is False
    assert boss_job_url_matches_expected(
        "https://evil.example/job_detail/job-a.html",
        expected,
    ) is False
