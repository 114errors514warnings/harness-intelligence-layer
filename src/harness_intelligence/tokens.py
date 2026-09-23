from __future__ import annotations


def estimate_tokens(text: str) -> int:
    """Cheap conservative estimate that handles CJK better than len/4."""
    ascii_count = sum(ord(char) < 128 for char in text)
    non_ascii_count = len(text) - ascii_count
    return max(1, (ascii_count + 3) // 4 + non_ascii_count)

