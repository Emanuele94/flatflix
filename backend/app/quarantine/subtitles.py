"""Subtitle check, pure (D-62).

Subtitles are not probed in the VM. The caller reads at most `text_max_bytes` of the file with a
read-only open and passes them as `head`; the size caps are checked before the content (a huge
file is never decoded). A text subtitle (.srt, .ass, .ssa and the .idx index of a VobSub pair)
passes when it is non-empty, small enough, and free of NUL and control bytes. A `.sub` is either
text (MicroDVD) or a VobSub bitmap stream, which is an MPEG program stream and starts with the pack
header `00 00 01 BA`: it passes on one of those two, and only up to the bitmap size cap. Anything
else with those extensions is refused as binary (WR-07), because Jellyfin hands external subtitles
to ffmpeg and a size cap alone vouches for nothing.
"""

from app.download.allowlist import SUBTITLE_EXTENSIONS
from app.quarantine.rules import PASS, Verdict, fail

TEXT_EXTENSIONS = frozenset({".srt", ".ass", ".ssa", ".idx"})
BITMAP_EXTENSIONS = SUBTITLE_EXTENSIONS - TEXT_EXTENSIONS  # just ".sub"
# The first bytes of a VobSub .sub: an MPEG program stream pack header.
_VOBSUB_MAGIC = b"\x00\x00\x01\xba"
# Tab, line feed, form feed and carriage return are ordinary in subtitle text.
_ALLOWED_CONTROL = frozenset({9, 10, 12, 13})
# More than this share of control characters (1 %) means the file is not text.
_CONTROL_PERCENT = 1


def _codepoints(head: bytes) -> list[int] | None:
    """Code units of the text, or None when a UTF-16 file (BOM FF FE or FE FF) does not decode."""
    if head[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return [ord(c) for c in head.decode("utf-16")]
        except UnicodeDecodeError:
            return None
    if head.startswith(b"\xef\xbb\xbf"):
        head = head[3:]
    return list(head)


def _is_text(head: bytes) -> bool:
    units = _codepoints(head)
    if not units or 0 in units:
        return False
    controls = sum(1 for u in units if (u < 32 and u not in _ALLOWED_CONTROL) or u == 127)
    return controls * 100 <= _CONTROL_PERCENT * len(units)


def check_subtitle(
    extension: str, size: int, head: bytes, *, text_max_bytes: int, bitmap_max_bytes: int
) -> Verdict:
    extension = extension.lower()
    if extension not in SUBTITLE_EXTENSIONS:
        return fail("not_subtitle")
    if size <= 0:
        return fail("subtitle_empty")
    is_bitmap = extension in BITMAP_EXTENSIONS
    if is_bitmap:
        if size > bitmap_max_bytes:
            return fail("subtitle_too_big")
        if head.startswith(_VOBSUB_MAGIC):
            return PASS
    if size > text_max_bytes:
        # a .sub that is not a VobSub stream and too big to be a text one is not a subtitle
        return fail("subtitle_binary" if is_bitmap else "subtitle_too_big")
    if not head:
        return fail("subtitle_empty")  # the caller passed no bytes for a non-empty file
    return PASS if _is_text(head) else fail("subtitle_binary")
