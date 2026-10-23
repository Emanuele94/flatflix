"""Subtitle check (stub)."""

from app.quarantine.rules import PASS, Verdict


def check_subtitle(
    extension: str, size: int, head: bytes, *, text_max_bytes: int, bitmap_max_bytes: int
) -> Verdict:
    return PASS
