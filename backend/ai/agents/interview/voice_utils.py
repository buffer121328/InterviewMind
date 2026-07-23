"""Small utility functions for voice interview audio and transcripts."""

import struct
from typing import Dict, Optional


def pcm_to_wav(pcm_data: bytes, sample_rate=24000, num_channels=1, bits_per_sample=16) -> bytes:
    """将原始 PCM 数据转换为 WAV 格式。"""
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    data_size = len(pcm_data)

    wav_header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )
    return wav_header + pcm_data


def normalize_voice_transcript(
    text: Optional[str],
    term_fixes: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """整理浏览器转写文本，并应用显式配置的术语纠错。"""
    if text is None:
        return None

    normalized = " ".join(text.split())
    for source, target in sorted(
        (term_fixes or {}).items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if source:
            normalized = normalized.replace(source, target)
    return normalized
