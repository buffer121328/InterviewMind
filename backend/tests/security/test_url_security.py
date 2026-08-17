import socket

import pytest

from app.security.url_security import UnsafeOutboundUrl, validate_outbound_url


def test_rejects_cloud_metadata_even_when_private_models_allowed():
    with pytest.raises(UnsafeOutboundUrl):
        validate_outbound_url("http://169.254.169.254/latest/meta-data", allow_private=True)


def test_private_model_url_requires_explicit_allowance(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 11434))],
    )

    with pytest.raises(UnsafeOutboundUrl):
        validate_outbound_url("http://localhost:11434/v1", allow_private=False)

    assert validate_outbound_url("http://localhost:11434/v1", allow_private=True)


def test_public_url_is_allowed(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )

    assert validate_outbound_url("https://example.com/jobs") == "https://example.com/jobs"


def test_rejects_credentials_in_url():
    with pytest.raises(UnsafeOutboundUrl):
        validate_outbound_url("https://user:pass@example.com")


def test_rejects_ipv6_loopback_and_private_literals():
    with pytest.raises(UnsafeOutboundUrl):
        validate_outbound_url("http://[::1]:11434/v1", allow_private=False)
    with pytest.raises(UnsafeOutboundUrl):
        validate_outbound_url("http://[fd00::1]/v1", allow_private=False)
    with pytest.raises(UnsafeOutboundUrl):
        # IPv4-mapped IPv6 loopback
        validate_outbound_url("http://[::ffff:127.0.0.1]/v1", allow_private=False)


def test_dns_resolution_with_any_private_address_is_rejected(monkeypatch):
    def resolve(*_args, **_kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.5", 443)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    with pytest.raises(UnsafeOutboundUrl):
        validate_outbound_url("https://mixed.example.test/v1", allow_private=False)
    assert validate_outbound_url("https://mixed.example.test/v1", allow_private=True)


def test_dns_resolution_all_public_addresses_allowed(monkeypatch):
    def resolve(*_args, **_kwargs):
        return [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:2800:220:1:248:1893:25c8:1946", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    assert validate_outbound_url("https://dualstack.example.test/v1", allow_private=False)
