import socket

import pytest

from app.services.url_security import UnsafeOutboundUrl, validate_outbound_url


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
