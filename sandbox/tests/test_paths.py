"""resolve_probe_path: no request can reach a file outside the quarantine root (T-02.1-05)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from runner.paths import InvalidPath, NotFound, NotRegular, resolve_probe_path


@pytest.fixture
def root(tmp_path: Path) -> Path:
    base = tmp_path / "quarantine"
    (base / "Film").mkdir(parents=True)
    (base / "Film" / "a.mkv").write_bytes(b"a")
    (base / "Film" / "b.mkv").write_bytes(b"b")
    (base / "Film" / ".hidden dir").mkdir()
    (base / "Film" / ".hidden dir" / "a.mkv").write_bytes(b"h")
    (base / "Film" / "Real").mkdir()
    (base / "Film" / "Real" / "c.mkv").write_bytes(b"c")
    return base


@pytest.mark.parametrize(
    "rel",
    [
        "",
        "/Film/a.mkv",
        "Film/../Film/a.mkv",
        "../x",
        "Film//a.mkv",
        "Film/./a.mkv",
        "Film\\a.mkv",
        "Film/a\x00.mkv",
        "Film/a.mkv/",
    ],
)
def test_malformed_paths_are_invalid(root: Path, rel: str) -> None:
    with pytest.raises(InvalidPath):
        resolve_probe_path(root, rel)


def test_a_plain_relative_file_resolves_to_its_real_path(root: Path) -> None:
    assert resolve_probe_path(root, "Film/a.mkv") == Path(os.path.realpath(root / "Film" / "a.mkv"))


def test_a_dot_prefixed_name_is_not_a_dot_segment(root: Path) -> None:
    resolved = resolve_probe_path(root, "Film/.hidden dir/a.mkv")
    assert resolved.name == "a.mkv"


def test_symlink_to_another_file_inside_the_root_is_refused(root: Path) -> None:
    os.symlink(root / "Film" / "b.mkv", root / "Film" / "link.mkv")
    with pytest.raises(InvalidPath):
        resolve_probe_path(root, "Film/link.mkv")


def test_symlink_to_a_file_outside_the_root_is_refused(root: Path, tmp_path: Path) -> None:
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    os.symlink(outside, root / "Film" / "out.mkv")
    with pytest.raises(InvalidPath):
        resolve_probe_path(root, "Film/out.mkv")


def test_symlinked_directory_segment_is_refused(root: Path) -> None:
    os.symlink(root / "Film" / "Real", root / "Film" / "Alias")
    with pytest.raises(InvalidPath):
        resolve_probe_path(root, "Film/Alias/c.mkv")


def test_a_symlinked_root_itself_is_not_a_hop(root: Path, tmp_path: Path) -> None:
    alias = tmp_path / "root-alias"
    os.symlink(root, alias)
    assert resolve_probe_path(alias, "Film/a.mkv").name == "a.mkv"


def test_a_missing_file_is_not_found(root: Path) -> None:
    with pytest.raises(NotFound):
        resolve_probe_path(root, "Film/missing.mkv")


def test_a_path_below_a_file_is_not_found(root: Path) -> None:
    with pytest.raises(NotFound):
        resolve_probe_path(root, "Film/a.mkv/deeper.mkv")


def test_a_directory_is_not_a_regular_file(root: Path) -> None:
    with pytest.raises(NotRegular):
        resolve_probe_path(root, "Film/Real")


def test_a_fifo_is_not_a_regular_file(root: Path) -> None:
    os.mkfifo(root / "Film" / "pipe.mkv")
    with pytest.raises(NotRegular):
        resolve_probe_path(root, "Film/pipe.mkv")
