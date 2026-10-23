"""The VM is always offline, read-only, limited and exact-sized (QUAR-02).

Unit level: the functions of runner.vm are called directly, against the stub
firecracker of conftest where a process is needed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from runner.vm import (
    RunnerConfig,
    build_config,
    facts_from_ffprobe,
    parse_console,
    probe_file,
    run_vm,
    write_tail,
)

NONCE = "0123456789abcdef"


def _cfg(tmp_path: Path, **overrides) -> RunnerConfig:
    return RunnerConfig(
        kernel=tmp_path / "vmlinux",
        rootfs=tmp_path / "rootfs.ext4",
        work_dir=tmp_path / "work",
        timeout_seconds=3,
        **overrides,
    )


# -- build_config -----------------------------------------------------------------------


def test_build_config_has_no_network_interfaces_anywhere(tmp_path: Path) -> None:
    config = build_config(_cfg(tmp_path), tmp_path / "f.mkv", tmp_path / "t.bin", NONCE, 5000)
    assert "network-interfaces" not in json.dumps(config)


def test_build_config_attaches_three_read_only_drives_with_rootfs_as_root(
    tmp_path: Path,
) -> None:
    cfg = _cfg(tmp_path)
    config = build_config(cfg, tmp_path / "f.mkv", tmp_path / "t.bin", NONCE, 5000)
    drives = config["drives"]
    assert [d["drive_id"] for d in drives] == ["rootfs", "probe", "tail"]
    assert [d["is_root_device"] for d in drives] == [True, False, False]
    assert all(d["is_read_only"] is True for d in drives)
    assert drives[0]["path_on_host"] == str(cfg.rootfs)
    assert drives[1]["path_on_host"] == str(tmp_path / "f.mkv")
    assert drives[2]["path_on_host"] == str(tmp_path / "t.bin")


def test_build_config_default_limits(tmp_path: Path) -> None:
    config = build_config(_cfg(tmp_path), tmp_path / "f.mkv", tmp_path / "t.bin", NONCE, 5000)
    assert config["machine-config"] == {"vcpu_count": 1, "mem_size_mib": 256, "smt": False}


def test_build_config_limits_follow_the_environment(tmp_path: Path) -> None:
    cfg = RunnerConfig.from_env({"VM_VCPUS": "2", "VM_MEMORY_MIB": "512"})
    config = build_config(cfg, tmp_path / "f.mkv", tmp_path / "t.bin", NONCE, 5000)
    assert config["machine-config"] == {"vcpu_count": 2, "mem_size_mib": 512, "smt": False}


def test_build_config_boot_args_carry_the_nonce_and_the_size(tmp_path: Path) -> None:
    config = build_config(_cfg(tmp_path), tmp_path / "f.mkv", tmp_path / "t.bin", NONCE, 1049087)
    args = config["boot-source"]["boot_args"]
    assert re.search(r"\bfxnonce=[0-9a-f]{16}\b", args)
    assert "fxnonce=" + NONCE in args
    assert args.endswith("fxsize=1049087")
    assert "root=/dev/vda ro init=/init" in args


def test_a_path_with_a_quote_and_a_space_round_trips_through_json(tmp_path: Path) -> None:
    odd = tmp_path / 'Film "Director\'s Cut"' / "a b.mkv"
    config = build_config(_cfg(tmp_path), odd, tmp_path / "t.bin", NONCE, 5000)
    assert json.loads(json.dumps(config))["drives"][1]["path_on_host"] == str(odd)


def test_from_env_defaults_match_the_contract() -> None:
    cfg = RunnerConfig.from_env({})
    assert cfg.quarantine_root == Path("/data/quarantine")
    assert cfg.firecracker == Path("/usr/local/bin/firecracker")
    assert (cfg.vcpus, cfg.memory_mib, cfg.timeout_seconds, cfg.port) == (1, 256, 60, 8090)
    assert (cfg.max_console_bytes, cfg.min_probe_bytes) == (262144, 4096)


# -- write_tail: the exact-bytes attach ------------------------------------------------


def _file_of(path: Path, size: int, last: bytes = b"\x00") -> Path:
    with open(path, "wb") as handle:
        handle.truncate(size)
        handle.seek(size - 1)
        handle.write(last)
    return path


def test_tail_of_an_exact_sector_multiple_is_512_zero_bytes(tmp_path: Path) -> None:
    src = _file_of(tmp_path / "f.bin", 1048576, b"\x41")
    dest = tmp_path / "tail.bin"
    write_tail(src, 1048576, dest)
    assert dest.read_bytes() == b"\x00" * 512


def test_tail_one_byte_past_a_boundary_is_that_byte_then_zeros(tmp_path: Path) -> None:
    src = _file_of(tmp_path / "f.bin", 1048577, b"\x41")
    dest = tmp_path / "tail.bin"
    write_tail(src, 1048577, dest)
    assert dest.read_bytes() == b"\x41" + b"\x00" * 511


def test_tail_of_511_leftover_bytes_ends_with_one_zero(tmp_path: Path) -> None:
    size = 1049087
    src = tmp_path / "f.bin"
    with open(src, "wb") as handle:
        handle.truncate(size - 511)
        handle.seek(size - 511)
        handle.write(b"\x07" * 511)
    dest = tmp_path / "tail.bin"
    write_tail(src, size, dest)
    assert dest.read_bytes() == b"\x07" * 511 + b"\x00"


# -- parse_console: the nonce is a trust boundary ---------------------------------------

FRAME = (
    'FXP:{n}:BEGIN\nFXP:{n}:EXIT:0\nFXP:{n}:JSON\n{{"format": {{}}}}\n'
    "FXP:{n}:ERR\nsome warning\nFXP:{n}:END\n"
)


def test_frames_of_another_nonce_are_ignored() -> None:
    other = FRAME.format(n="ffffffffffffffff")
    console = parse_console(other, NONCE)
    assert console.begin is False
    assert console.exit_code is None
    assert console.json_text == ""


def test_a_forged_block_before_the_real_one_changes_nothing() -> None:
    forged = FRAME.format(n="ffffffffffffffff")
    real = f"FXP:{NONCE}:BEGIN\nFXP:{NONCE}:EXIT:1\nFXP:{NONCE}:JSON\nFXP:{NONCE}:ERR\nFXP:{NONCE}:END\n"
    console = parse_console(forged + real, NONCE)
    assert console.begin is True
    assert console.exit_code == 1
    assert console.json_text == ""


def test_crlf_line_endings_are_handled() -> None:
    text = FRAME.format(n=NONCE).replace("\n", "\r\n")
    console = parse_console(text, NONCE)
    assert (console.begin, console.exit_code, console.ended) == (True, 0, True)
    assert json.loads(console.json_text) == {"format": {}}


def test_a_missing_end_still_yields_begin_exit_and_json() -> None:
    text = FRAME.format(n=NONCE).replace(f"FXP:{NONCE}:END\n", "")
    console = parse_console(text, NONCE)
    assert (console.begin, console.exit_code, console.ended) == (True, 0, False)
    assert json.loads(console.json_text) == {"format": {}}


def test_stderr_is_cut_to_1024_characters() -> None:
    text = f"FXP:{NONCE}:BEGIN\nFXP:{NONCE}:ERR\n" + "e" * 5000 + f"\nFXP:{NONCE}:END\n"
    assert len(parse_console(text, NONCE).stderr_text) == 1024


def test_non_printable_stderr_characters_become_question_marks() -> None:
    text = f"FXP:{NONCE}:ERR\nbad \x1b[31mred\x00\x7f\xe9 end\nFXP:{NONCE}:END\n"
    assert parse_console(text, NONCE).stderr_text == "bad ?[31mred??? end"


# -- facts_from_ffprobe ---------------------------------------------------------------


def test_facts_keep_ffprobe_stream_order_and_only_the_contract_keys() -> None:
    obj = {
        "format": {
            "format_name": "avi",
            "duration": "1.5",
            "nb_streams": 3,
            "size": "9",
            "tags": {"x": "y"},
            "filename": "secret",
        },
        "streams": [
            {"index": 0, "codec_type": "audio", "codec_name": "mp3", "tags": {"a": "b"}},
            {
                "index": 1,
                "codec_type": "video",
                "codec_name": "mjpeg",
                "width": 10,
                "height": 20,
                "disposition": {"attached_pic": 1},
            },
            {
                "index": 2,
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1,
                "height": 2,
                "disposition": {"attached_pic": 0},
                "bit_rate": "5",
            },
        ],
    }
    fmt, streams = facts_from_ffprobe(obj)
    assert fmt == {"format_name": "avi", "duration": "1.5", "nb_streams": 3, "size": "9"}
    assert [s["index"] for s in streams] == [0, 1, 2]
    assert [s["attached_pic"] for s in streams] == [False, True, False]
    assert set(streams[0]) == {
        "index",
        "codec_type",
        "codec_name",
        "attached_pic",
        "width",
        "height",
    }
    assert streams[1]["width"] == 10


# -- run_vm / probe_file against the stub ---------------------------------------------


def _run(tmp_path: Path, stub, monkeypatch, mode: str, **overrides):
    monkeypatch.setenv("STUB_MODE", mode)
    cfg = _cfg(tmp_path, firecracker=stub.path, **overrides)
    workdir = tmp_path / "wd"
    workdir.mkdir()
    tail = workdir / "tail.bin"
    tail.write_bytes(b"\x00" * 512)
    config = build_config(cfg, tmp_path / "f.mkv", tail, NONCE, 5000)
    return run_vm(cfg, config, workdir, NONCE)


def test_a_flood_of_console_output_is_capped_and_does_not_hang(
    tmp_path: Path, stub_firecracker, monkeypatch
) -> None:
    result = _run(tmp_path, stub_firecracker, monkeypatch, "flood", max_console_bytes=65536)
    assert result.timed_out is False
    assert result.console_len <= 65536
    assert result.begin_seen is False


def test_the_spoofed_block_never_beats_the_real_frame(
    tmp_path: Path, stub_firecracker, monkeypatch
) -> None:
    result = _run(tmp_path, stub_firecracker, monkeypatch, "spoof")
    assert result.begin_seen is True
    assert result.exit_code == 1
    assert result.json_text == ""


def test_probe_file_reports_a_spoofed_ok_as_probe_failed(
    tmp_path: Path, stub_firecracker, monkeypatch
) -> None:
    monkeypatch.setenv("STUB_MODE", "spoof")
    movie = _file_of(tmp_path / "movie.mkv", 1048576)
    answer = probe_file(_cfg(tmp_path, firecracker=stub_firecracker.path), movie)
    assert (answer["status"], answer["reason"]) == ("probe_failed", "exit")


def test_probe_file_generates_a_fresh_16_hex_nonce_per_vm(tmp_path: Path, stub_firecracker) -> None:
    movie = _file_of(tmp_path / "movie.mkv", 1048576)
    cfg = _cfg(tmp_path, firecracker=stub_firecracker.path)
    probe_file(cfg, movie)
    probe_file(cfg, movie)
    nonces = [
        re.search(r"fxnonce=([0-9a-f]{16})\b", c["boot-source"]["boot_args"]).group(1)
        for c in stub_firecracker.configs()
    ]
    assert len(set(nonces)) == 2


def test_a_file_on_a_sector_boundary_gets_a_zero_tail_and_its_exact_size(
    tmp_path: Path, stub_firecracker
) -> None:
    movie = _file_of(tmp_path / "movie.mkv", 1048576, b"\x41")
    answer = probe_file(_cfg(tmp_path, firecracker=stub_firecracker.path), movie)
    assert answer["status"] == "ok"
    assert answer["size_bytes"] == 1048576
    assert stub_firecracker.configs()[0]["boot-source"]["boot_args"].endswith("fxsize=1048576")
    assert stub_firecracker.tail() == b"\x00" * 512


def test_a_file_one_byte_past_a_boundary_gets_its_last_byte_in_the_tail(
    tmp_path: Path, stub_firecracker
) -> None:
    movie = _file_of(tmp_path / "movie.mkv", 1048577, b"\x41")
    answer = probe_file(_cfg(tmp_path, firecracker=stub_firecracker.path), movie)
    assert answer["status"] == "ok"
    assert stub_firecracker.configs()[0]["boot-source"]["boot_args"].endswith("fxsize=1048577")
    assert stub_firecracker.tail() == b"\x41" + b"\x00" * 511


def test_the_work_dir_is_clean_after_a_probe(tmp_path: Path, stub_firecracker) -> None:
    movie = _file_of(tmp_path / "movie.mkv", 1048576)
    cfg = _cfg(tmp_path, firecracker=stub_firecracker.path)
    probe_file(cfg, movie)
    assert list(cfg.work_dir.iterdir()) == []


@pytest.mark.parametrize("size", [0, 1, 2000, 4095])
def test_a_tiny_file_is_too_small_and_starts_no_vm(
    tmp_path: Path, stub_firecracker, size: int
) -> None:
    movie = tmp_path / "tiny.mkv"
    movie.write_bytes(b"\x00" * size)
    answer = probe_file(_cfg(tmp_path, firecracker=stub_firecracker.path), movie)
    assert (answer["status"], answer["reason"]) == ("probe_failed", "too_small")
    assert answer["size_bytes"] == size
    assert stub_firecracker.configs() == []


def test_a_file_of_exactly_the_minimum_size_is_probed(tmp_path: Path, stub_firecracker) -> None:
    movie = tmp_path / "min.mkv"
    movie.write_bytes(b"\x00" * 4096)
    answer = probe_file(_cfg(tmp_path, firecracker=stub_firecracker.path), movie)
    assert answer["status"] == "ok"
