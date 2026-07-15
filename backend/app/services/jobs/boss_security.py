"""BOSS 自动化进程间共享的无状态安全规则。"""

from urllib.parse import urlparse


def is_allowed_apply_url(value: str) -> bool:
    """自动化只允许 BOSS 直聘官方 HTTPS 域名。"""

    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (
        hostname == "zhipin.com" or hostname.endswith(".zhipin.com")
    )
