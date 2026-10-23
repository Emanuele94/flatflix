"""The runner's HTTP contract, driven end to end against a stub firecracker.

POST /probe resolves a path under the quarantine root only, boots one VM per
request and answers plain facts; the runner never judges them (D-69, D-70).
"""

from __future__ import annotations

import os
import signal
import threading
import time

import pytest


def test_probe_boots_one_vm_and_answers_the_facts_contract(runner, stub_firecracker):
    status, body = runner.probe("Film/Movie/movie.mkv")

    assert status == 200
    assert body["status"] == "ok"
    assert body["reason"] is None
    assert body["ffprobe_exit"] == 0
    assert body["size_bytes"] == 2097152
    assert body["ffmpeg"] == "8.1.2-r0"
    assert body["format"]["format_name"] == "matroska,webm"
    video = body["streams"][0]
    assert (video["codec_type"], video["codec_name"]) == ("video", "h264")
    assert video["attached_pic"] is False

    configs = stub_firecracker.configs()
    assert len(configs) == 1
    assert "network-interfaces" not in configs[0]
    assert len(configs[0]["drives"]) == 3
    assert all(drive["is_read_only"] is True for drive in configs[0]["drives"])


# -- path and body errors -----------------------------------------------------------------

AS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0


@pytest.mark.parametrize(
    ("path", "status", "error"),
    [
        ("", 400, "invalid_path"),
        ("/etc/passwd", 400, "invalid_path"),
        ("../outside.mkv", 400, "invalid_path"),
        ("Film/missing.mkv", 404, "not_found"),
        ("Film/Movie", 409, "not_regular_file"),
    ],
)
def test_path_errors_use_the_documented_codes(runner, path, status, error):
    assert runner.probe(path) == (status, {"error": error})


def test_a_symlink_in_the_quarantine_is_an_invalid_path(runner):
    os.symlink(runner.quarantine / "Film" / "Movie" / "movie.mkv", runner.quarantine / "link.mkv")
    assert runner.probe("link.mkv") == (400, {"error": "invalid_path"})


@pytest.mark.parametrize(
    "raw",
    [b"x" * 5000, b'{"path": "' + b"a" * 5000 + b'"}', b'["Film/a.mkv"]', b'{"path": 3}', b"{nope"],
)
def test_an_unusable_body_is_invalid_json(runner, raw):
    assert runner.request("POST", "/probe", raw=raw) == (400, {"error": "invalid_json"})


def test_unknown_routes_are_not_found(runner):
    assert runner.request("GET", "/nope") == (404, {"error": "not_found"})
    assert runner.request("POST", "/nope", {"path": "x"}) == (404, {"error": "not_found"})


# -- file faults are reported ---------------------------------------------------------------


@pytest.mark.parametrize("size", [0, 2000])
def test_a_tiny_file_is_too_small_and_no_vm_starts(runner, stub_firecracker, size):
    tiny = runner.quarantine / "Film" / "tiny.mkv"
    tiny.write_bytes(b"\x00" * size)
    status, body = runner.probe("Film/tiny.mkv")
    assert status == 200
    assert (body["status"], body["reason"]) == ("probe_failed", "too_small")
    assert stub_firecracker.configs() == []


def test_a_non_zero_exit_is_probe_failed_exit(runner, monkeypatch):
    monkeypatch.setenv("STUB_MODE", "nonzero")
    status, body = runner.probe("Film/Movie/movie.mkv")
    assert status == 200
    assert (body["status"], body["reason"], body["ffprobe_exit"]) == ("probe_failed", "exit", 1)
    assert body["stderr"] == "Invalid data found when processing input"


def test_missing_json_is_probe_failed_no_json(runner, monkeypatch):
    monkeypatch.setenv("STUB_MODE", "badjson")
    status, body = runner.probe("Film/Movie/movie.mkv")
    assert status == 200
    assert (body["status"], body["reason"]) == ("probe_failed", "no_json")


def test_a_timeout_after_begin_is_reported_and_the_whole_process_group_is_gone(
    make_runner, stub_firecracker, monkeypatch
):
    monkeypatch.setenv("STUB_MODE", "sleep")
    runner = make_runner(timeout_seconds=1)
    started = time.monotonic()
    try:
        status, body = runner.probe("Film/Movie/movie.mkv")
        elapsed = time.monotonic() - started
        assert status == 200
        assert body["status"] == "timeout"
        assert elapsed < 3
        pids = [int(stub_firecracker.number("pid")[0]), int(stub_firecracker.number("child")[0])]
        for pid in pids:
            assert _gone(pid), f"process {pid} survived the timeout"
        assert list(runner.cfg.work_dir.iterdir()) == []
    finally:
        for pid in stub_firecracker.number("child"):
            try:
                os.kill(int(pid), signal.SIGKILL)
            except ProcessLookupError:
                pass


def _gone(pid: int, wait: float = 2.0) -> bool:
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


# -- host faults are 503, never a verdict ------------------------------------------------------

UNAVAILABLE = "runner_unavailable"


def test_no_begin_line_is_a_boot_fault(runner, monkeypatch):
    monkeypatch.setenv("STUB_MODE", "noboot")
    assert runner.probe("Film/Movie/movie.mkv") == (503, {"error": UNAVAILABLE, "why": "boot"})


def test_a_hang_before_begin_is_a_boot_fault(make_runner, monkeypatch):
    monkeypatch.setenv("STUB_MODE", "hang_before_begin")
    runner = make_runner(timeout_seconds=1)
    assert runner.probe("Film/Movie/movie.mkv") == (503, {"error": UNAVAILABLE, "why": "boot"})


@pytest.mark.parametrize("artifact", ["firecracker", "kernel", "rootfs"])
def test_a_missing_artifact_is_503_and_no_vm_starts(
    make_runner, stub_firecracker, tmp_path, artifact
):
    runner = make_runner(**{artifact: tmp_path / "does-not-exist"})
    assert runner.probe("Film/Movie/movie.mkv") == (503, {"error": UNAVAILABLE, "why": "artifacts"})
    assert stub_firecracker.configs() == []


def test_a_missing_kvm_device_is_503_kvm(make_runner, stub_firecracker, tmp_path):
    runner = make_runner(kvm_device=tmp_path / "no-kvm")
    assert runner.probe("Film/Movie/movie.mkv") == (503, {"error": UNAVAILABLE, "why": "kvm"})
    assert stub_firecracker.configs() == []


@pytest.mark.skipif(AS_ROOT, reason="root can open any file")
def test_an_unreadable_kvm_device_is_503_kvm(make_runner):
    runner = make_runner()
    runner.cfg.kvm_device.chmod(0)
    assert runner.probe("Film/Movie/movie.mkv") == (503, {"error": UNAVAILABLE, "why": "kvm"})


@pytest.mark.skipif(AS_ROOT, reason="root can open any file")
def test_an_unreadable_quarantined_file_is_503_permission(runner, stub_firecracker):
    movie = runner.quarantine / "Film" / "Movie" / "movie.mkv"
    movie.chmod(0)
    try:
        assert runner.probe("Film/Movie/movie.mkv") == (
            503,
            {"error": UNAVAILABLE, "why": "permission"},
        )
    finally:
        movie.chmod(0o644)
    assert stub_firecracker.configs() == []


@pytest.mark.skipif(AS_ROOT, reason="root can open any file")
def test_an_untraversable_folder_is_503_permission(runner):
    folder = runner.quarantine / "Film" / "Movie"
    folder.chmod(0)
    try:
        assert runner.probe("Film/Movie/movie.mkv") == (
            503,
            {"error": UNAVAILABLE, "why": "permission"},
        )
    finally:
        folder.chmod(0o755)


def test_an_unusable_work_dir_is_503(make_runner, tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where the work dir should go")
    runner = make_runner(work_dir=blocker / "work")
    assert runner.probe("Film/Movie/movie.mkv") == (503, {"error": UNAVAILABLE, "why": "artifacts"})


# -- one VM at a time -----------------------------------------------------------------------


def test_two_parallel_probes_run_one_vm_at_a_time(runner, stub_firecracker, monkeypatch):
    monkeypatch.setenv("STUB_MODE", "slow")
    results: list[tuple[int, dict]] = []

    def call() -> None:
        results.append(runner.probe("Film/Movie/movie.mkv"))

    threads = [threading.Thread(target=call) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert [status for status, _ in results] == [200, 200]
    assert [body["status"] for _, body in results] == ["ok", "ok"]
    starts, stops = stub_firecracker.number("start"), stub_firecracker.number("stop")
    assert len(starts) == len(stops) == 2
    assert stops[0] <= starts[1]


# -- health and selftest ----------------------------------------------------------------------


def test_health_reports_versions_and_kvm(runner):
    assert runner.request("GET", "/health") == (
        200,
        {
            "ok": True,
            "kvm": True,
            "firecracker": "1.17.0",
            "kernel": "6.18.58",
            "alpine": "3.24.3",
            "ffmpeg": "8.1.2-r0",
        },
    )


def test_health_without_a_versions_file_says_unknown(make_runner, tmp_path):
    runner = make_runner(versions_file=tmp_path / "absent")
    status, body = runner.request("GET", "/health")
    assert status == 200
    assert {body[k] for k in ("firecracker", "kernel", "alpine", "ffmpeg")} == {"unknown"}


def test_health_without_kvm_is_still_ok(make_runner, tmp_path):
    runner = make_runner(kvm_device=tmp_path / "no-kvm")
    status, body = runner.request("GET", "/health")
    assert (status, body["ok"], body["kvm"]) == (200, True, False)


def test_selftest_probes_the_baked_in_clip(runner, stub_firecracker):
    status, body = runner.request("POST", "/selftest")
    assert status == 200
    assert body["status"] == "ok"
    assert body["size_bytes"] == 8192
    assert body["ffmpeg"] == "8.1.2-r0"
    assert stub_firecracker.configs()[0]["drives"][1]["path_on_host"] == str(
        runner.cfg.selftest_file
    )


def test_selftest_without_its_clip_is_503_artifacts(make_runner, tmp_path):
    runner = make_runner(selftest_file=tmp_path / "absent.mkv")
    assert runner.request("POST", "/selftest") == (
        503,
        {"error": UNAVAILABLE, "why": "artifacts"},
    )
