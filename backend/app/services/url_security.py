"""服务端出站 URL 安全校验。"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeOutboundUrl(ValueError):
    """URL 协议、主机或解析地址不符合出站访问策略。"""


_BLOCKED_HOSTS = {
    "metadata.google.internal",
    "metadata.google",
    "instance-data",
}


def _is_blocked_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address, *, allow_private: bool) -> bool:
    # 链路本地地址包含常见云元数据端点，即使允许本地模型也始终拒绝。
    if address.is_link_local or address.is_multicast or address.is_unspecified or address.is_reserved:
        return True
    if not allow_private and (address.is_private or address.is_loopback):
        return True
    return False


def validate_outbound_url(
    value: str,
    *,
    allow_private: bool = False,
    allowed_schemes: tuple[str, ...] = ("http", "https"),
) -> str:
    """校验 URL 语法并解析主机，拒绝危险的服务端出站目标。"""
    parsed = urlparse(value.strip())
    if parsed.scheme.lower() not in allowed_schemes:
        raise UnsafeOutboundUrl("仅允许 HTTP/HTTPS 地址")
    if not parsed.hostname:
        raise UnsafeOutboundUrl("URL 缺少有效主机名")
    if parsed.username or parsed.password:
        raise UnsafeOutboundUrl("URL 不允许包含用户名或密码")

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in _BLOCKED_HOSTS or hostname.endswith(".internal") and not allow_private:
        raise UnsafeOutboundUrl("URL 指向受限内部主机")

    try:
        addresses = [ipaddress.ip_address(hostname)]
    except ValueError:
        try:
            infos = socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise UnsafeOutboundUrl("URL 主机名无法解析") from exc
        addresses = list({ipaddress.ip_address(item[4][0]) for item in infos})

    if not addresses or any(_is_blocked_address(address, allow_private=allow_private) for address in addresses):
        raise UnsafeOutboundUrl("URL 指向不允许访问的网络地址")
    return value
