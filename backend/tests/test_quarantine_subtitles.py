"""check_subtitle: subtitles never go to the VM, they get a size and a text check (D-62)."""

import pytest

from app.quarantine.rules import PASS, Verdict
from app.quarantine.subtitles import check_subtitle

TEXT_MAX = 5 * 1024 * 1024
BITMAP_MAX = 200 * 1024 * 1024
SRT = b"1\n00:00:01,000 --> 00:00:02,000\nHello\n"


def check(extension: str, head: bytes, size: int | None = None) -> Verdict:
    return check_subtitle(
        extension,
        len(head) if size is None else size,
        head,
        text_max_bytes=TEXT_MAX,
        bitmap_max_bytes=BITMAP_MAX,
    )


def test_a_plain_srt_passes() -> None:
    assert (
        check_subtitle(".srt", 2_000, SRT, text_max_bytes=TEXT_MAX, bitmap_max_bytes=BITMAP_MAX)
        == PASS
    )


def test_latin1_accented_text_passes() -> None:
    assert (
        check(".srt", "1\n00:00:01,000 --> 00:00:02,000\nCaffè e perché\n".encode("latin-1"))
        == PASS
    )


def test_utf16_with_a_bom_passes() -> None:
    assert check(".srt", SRT.decode().encode("utf-16")) == PASS
    assert check(".srt", b"\xfe\xff" + SRT.decode().encode("utf-16-be")) == PASS


def test_a_utf8_bom_is_skipped() -> None:
    assert check(".srt", b"\xef\xbb\xbf" + SRT) == PASS


def test_utf16_that_does_not_decode_is_binary() -> None:
    assert check(".srt", b"\xff\xfe\x00\xd8\x41") == Verdict(False, "subtitle_binary")


@pytest.mark.parametrize(
    "head",
    [
        SRT + b"\x00" + SRT,
        b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 8 + b"\x03\x00>\x00",
        b"\x01" * 3 + SRT * 5,
    ],
    ids=["nul", "elf", "control-bytes"],
)
def test_binary_content_is_refused(head) -> None:
    assert check(".srt", head) == Verdict(False, "subtitle_binary")


def test_a_few_control_bytes_below_one_percent_still_pass() -> None:
    head = SRT * 40 + b"\x01"  # well under 1 %
    assert check(".srt", head) == PASS


def test_tab_lf_cr_and_ff_are_not_control_bytes() -> None:
    assert check(".srt", b"a\tb\r\nc\x0cd\n" * 50) == PASS


def test_an_empty_file_is_refused() -> None:
    assert check(".srt", b"", size=0) == Verdict(False, "subtitle_empty")
    assert check(".sub", b"", size=0) == Verdict(False, "subtitle_empty")


def test_text_size_cap_is_inclusive() -> None:
    assert check(".srt", SRT, size=TEXT_MAX) == PASS
    assert check(".srt", SRT, size=TEXT_MAX + 1) == Verdict(False, "subtitle_too_big")


def test_the_size_cap_is_checked_before_the_content() -> None:
    assert check(".srt", b"\x00" * 10, size=TEXT_MAX + 1) == Verdict(False, "subtitle_too_big")


@pytest.mark.parametrize("extension", [".sub", ".idx"])
def test_bitmap_subtitles_pass_on_a_size_cap_only(extension) -> None:
    binary = bytes(range(256)) * 4
    assert check(extension, binary) == PASS
    assert check(extension, binary, size=BITMAP_MAX) == PASS
    assert check(extension, binary, size=BITMAP_MAX + 1) == Verdict(False, "subtitle_too_big")


@pytest.mark.parametrize("extension", [".ass", ".ssa"])
def test_ass_and_ssa_follow_the_text_rules(extension) -> None:
    assert check(extension, b"[Script Info]\nTitle: x\n") == PASS
    assert check(extension, b"[Script Info]\x00") == Verdict(False, "subtitle_binary")
    assert check(extension, b"x", size=TEXT_MAX + 1) == Verdict(False, "subtitle_too_big")


def test_the_extension_is_case_insensitive() -> None:
    assert check(".SRT", SRT) == PASS


def test_a_video_is_not_a_subtitle() -> None:
    assert check(".mkv", SRT) == Verdict(False, "not_subtitle")
    assert check("", SRT) == Verdict(False, "not_subtitle")
