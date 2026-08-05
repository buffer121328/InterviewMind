"""Lossless context assembly for authoritative JD, resume, and current-Q&A sources."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class AuthoritativeContext:
    """Model context plus credential-free integrity metadata."""

    model_context: str
    metadata: dict[str, Any]


def _serialize(value: Any) -> str:
    """Serialize structured authoritative sources deterministically without lossy summarization."""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def assemble_authoritative_context(
    *,
    agent_name: str,
    sources: Mapping[str, Any],
) -> AuthoritativeContext:
    """Assemble every authoritative source in full and expose source-version fingerprints."""
    blocks: list[str] = []
    fingerprints: dict[str, str] = {}
    source_breakdown: dict[str, int] = {}
    for name, value in sources.items():
        text = _serialize(value)
        blocks.append(f"【{name}】\n{text}")
        source_breakdown[name] = len(text)
        fingerprints[name] = sha256(text.encode("utf-8")).hexdigest()
    return AuthoritativeContext(
        model_context="\n\n".join(blocks),
        metadata={
            "agent_name": agent_name,
            "source_breakdown": source_breakdown,
            "source_fingerprints": fingerprints,
            "authoritative_source_truncated": False,
            "overflow_strategy": "lossless_segments_or_derived_ir",
        },
    )
