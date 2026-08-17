"""Keep the local Compose deployment locked to loopback-only network exposure."""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


_SERVICES = ("postgres", "redis", "migrate", "backend", "worker", "frontend", "nginx")


def _service_block(service: str) -> str:
    """Return the raw YAML block for one top-level compose service."""

    lines = (_REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8").splitlines()
    marker = f"  {service}:"
    start = next((index for index, line in enumerate(lines) if line == marker), None)
    assert start is not None, f"compose 服务 {service} 不存在"
    block = [lines[start]]
    for line in lines[start + 1 :]:
        if not line.startswith(" "):
            break
        if line in {f"  {name}:" for name in _SERVICES}:
            break
        block.append(line)
    return "\n".join(block)


def test_nginx_publish_is_loopback_only() -> None:
    """The unauthenticated web entry must never bind to all interfaces."""

    block = _service_block("nginx")
    assert "ports:" in block
    assert "127.0.0.1:${NGINX_PORT:-80}:80" in block
    assert '"80:80"' not in block


def test_storage_services_bind_loopback_only() -> None:
    """PostgreSQL and Redis keep their existing loopback bindings."""

    for service in ("postgres", "redis"):
        block = _service_block(service)
        assert "ports:" in block
        assert "127.0.0.1:" in block


def test_app_services_publish_no_host_ports() -> None:
    """Backend, worker, frontend and migrate stay inside the compose network."""

    for service in ("backend", "worker", "frontend", "migrate"):
        assert "ports:" not in _service_block(service)


def test_env_example_declares_local_only_usage() -> None:
    """The canonical template documents the machine-local scope and the nginx port."""

    template = (_REPO_ROOT / "env_example").read_text(encoding="utf-8")
    assert "NGINX_PORT" in template
    assert "仅限本机" in template
    assert "网络暴露" in template


def test_readme_states_exposure_upgrade_gate() -> None:
    """READMEs warn that network exposure triggers a mandatory auth migration."""

    for name in ("README.md", "README.local.md"):
        text = (_REPO_ROOT / name).read_text(encoding="utf-8")
        assert "仅限本机" in text
        assert "网络暴露" in text
        assert "认证" in text
