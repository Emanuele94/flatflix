"""The doctor's sandbox, storage and legacy checks (QUAR-01, QUAR-05, D-48, D-58, D-60, D-79).

FakeRunner stands in for the sandbox service, and a temporary DATA_PATH for the host folders.
Every line is checked for names, counts and versions only: no password, key, hash or torrent name.
"""

import errno
import os
from pathlib import Path

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.quarantine.runner_client import RunnerClient
from app.tools import doctor
from tests.conftest import PORTAL_PASS_HASH, QBIT_PASS, QBIT_USER
from tests.fakerunner import FakeRunner, failed_facts

SECRET = "test-secret-key-0123456789abcdefghij"
HASH = "c" * 40
NAME = "Sintel.2010.1080p.mkv"


def make_settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    return Settings(
        qbittorrent_url="http://qbittorrent.test:8088",
        qbittorrent_user=QBIT_USER,
        qbittorrent_pass=SecretStr(QBIT_PASS),
        app_user="famiglia-test",
        app_pass_hash=SecretStr(PORTAL_PASS_HASH),
        secret_key=SecretStr(SECRET),
        data_path=str(data),
        save_path_film=str(data / "quarantine" / "Film"),
        save_path_tv=str(data / "quarantine" / "SerieTV"),
        incomplete_path=str(data / "incomplete"),
    )


def make_tree(settings: Settings) -> None:
    for folder in (settings.quarantine_root, settings.media_root, settings.rejected_root):
        Path(folder).mkdir(parents=True, exist_ok=True)


def runner_client(fake: FakeRunner) -> RunnerClient:
    return RunnerClient("http://sandbox.test:8090", timeout=5, transport=fake.transport)


def texts(checks: list[doctor.Check]) -> list[str]:
    return [text for _, text in checks]


def leftovers(settings: Settings) -> list[str]:
    return sorted(
        entry.name
        for folder in (settings.quarantine_root, settings.media_root)
        for entry in Path(folder).iterdir()
    )


# -- the runner ------------------------------------------------------------------------------


async def test_a_healthy_sandbox_prints_its_versions_and_a_selftest_ok() -> None:
    client = runner_client(FakeRunner())

    checks = await doctor.sandbox_checks(client)

    assert checks == [
        (
            True,
            (
                "sandbox runner reachable, kvm True, firecracker 1.17.0, kernel 6.18.58, "
                "ffmpeg 8.1.2-r0"
            ),
        ),
        (True, "sandbox selftest ok"),
    ]
    await client.aclose()


async def test_an_unreachable_runner_is_one_fail_line_and_no_selftest() -> None:
    fake = FakeRunner()
    fake.unreachable = True
    client = runner_client(fake)

    checks = await doctor.sandbox_checks(client)

    assert checks == [(False, "sandbox runner not reachable (unreachable)")]
    await client.aclose()


async def test_a_runner_without_kvm_points_to_kvm_gid_and_runs_no_selftest() -> None:
    fake = FakeRunner()
    fake.health_body = {**fake.health_body, "kvm": False}
    client = runner_client(fake)

    checks = await doctor.sandbox_checks(client)

    assert checks == [(False, "sandbox cannot use /dev/kvm: check KVM_GID and docs/setup.md")]
    await client.aclose()


@pytest.mark.parametrize(
    ("answer", "token"),
    [
        (failed_facts("probe_failed"), "probe_failed"),
        (failed_facts("timeout"), "timeout"),
        (("down", "kvm"), "kvm"),
        (500, "server_error"),
    ],
)
async def test_a_failing_selftest_is_a_fail_line_with_a_token_only(answer, token: str) -> None:
    fake = FakeRunner()
    fake.script_selftest(answer)
    client = runner_client(fake)

    checks = await doctor.sandbox_checks(client)

    assert checks[0][0] is True
    assert checks[1] == (False, f"sandbox selftest failed ({token})")
    await client.aclose()


# -- the filesystem and the held files -------------------------------------------------------


def test_one_filesystem_and_a_working_hardlink_are_ok_and_leave_nothing_behind(
    tmp_path: Path,
) -> None:
    settings = make_settings(tmp_path)
    make_tree(settings)

    checks = doctor.storage_checks(settings)

    assert (True, "quarantine and media are on one filesystem") in checks
    assert (True, "hardlink quarantine -> media works") in checks
    assert all(ok for ok, _ in checks)
    assert leftovers(settings) == []


def test_media_on_another_device_fails_naming_the_cross_device_problem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = make_settings(tmp_path)
    make_tree(settings)
    real_stat = os.stat

    def fake_stat(path, *args, **kwargs):
        result = real_stat(path, *args, **kwargs)
        if os.fspath(path) == settings.media_root:
            return os.stat_result((*tuple(result)[:2], result.st_dev + 1, *tuple(result)[3:]))
        return result

    monkeypatch.setattr(doctor.os, "stat", fake_stat)

    checks = doctor.storage_checks(settings)

    failed = [text for ok, text in checks if not ok]
    assert any("different filesystems" in text and "EXDEV" in text for text in failed)
    assert leftovers(settings) == []


def test_a_link_that_the_kernel_refuses_reports_the_errno_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = make_settings(tmp_path)
    make_tree(settings)

    def refuse(*args, **kwargs):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(doctor.os, "link", refuse)

    checks = doctor.storage_checks(settings)

    assert (False, "hardlink quarantine -> media failed (EXDEV)") in checks
    assert leftovers(settings) == []


def test_a_missing_folder_is_a_fail_line_not_a_crash(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)

    checks = doctor.storage_checks(settings)

    assert not all(ok for ok, _ in checks)
    assert any("ENOENT" in text for _, text in checks)


def test_held_files_are_counted_and_sidecars_are_not(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    make_tree(settings)
    held = Path(settings.rejected_root) / "abc"
    (held / "sub").mkdir(parents=True)
    (held / "one.mkv").write_bytes(b"x")
    (held / "sub" / "two.mkv").write_bytes(b"x")
    (Path(settings.rejected_root) / "abc.json").write_text("{}")
    (held / "link").symlink_to(held / "one.mkv")

    checks = doctor.storage_checks(settings)

    assert (True, "2 file(s) held in rejected (purged after 7 days)") in checks


def test_no_held_files_reads_zero(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    make_tree(settings)

    checks = doctor.storage_checks(settings)

    assert (True, "0 file(s) held in rejected (purged after 7 days)") in checks


# -- torrents saved outside quarantine -------------------------------------------------------


def test_legacy_note_counts_film_and_series_torrents_outside_quarantine(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    rows = [
        {"hash": HASH, "name": NAME, "category": "Film", "save_path": "/data/media/Film"},
        {"hash": "d" * 40, "name": NAME, "category": "SerieTV", "save_path": "/media/SerieTV"},
        {
            "hash": "e" * 40,
            "name": NAME,
            "category": "Film",
            "save_path": f"{settings.quarantine_root}/Film",
        },
        {"hash": "f" * 40, "name": NAME, "category": "Music", "save_path": "/elsewhere"},
        {"hash": "9" * 40, "name": NAME, "category": "", "save_path": "/elsewhere"},
    ]

    ok, text = doctor.legacy_note(rows, settings)

    assert ok is True
    assert text.startswith("note: 2 Film/SerieTV torrent(s) save outside quarantine")
    assert "never checked" in text
    assert NAME not in text and HASH not in text


def test_legacy_note_with_nothing_outside_says_zero(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)

    ok, text = doctor.legacy_note([], settings)

    assert ok is True
    assert text.startswith("note: 0 Film/SerieTV torrent(s) save outside quarantine")


# -- run() -----------------------------------------------------------------------------------


class Spy:
    """Records the aclose calls of a client."""

    def __init__(self) -> None:
        self.closed = 0

    async def aclose(self) -> None:
        self.closed += 1


async def test_run_closes_the_runner_client_even_when_a_check_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = make_settings(tmp_path)
    runner_spy = Spy()
    monkeypatch.setattr(doctor, "RunnerClient", lambda *a, **k: runner_spy)

    async def boom(_runner):
        raise RuntimeError("boom")

    async def fine(_qbit, _settings):
        return [(True, "qbit fine")]

    monkeypatch.setattr(doctor, "sandbox_checks", boom)
    monkeypatch.setattr(doctor, "collect", fine)
    monkeypatch.setattr(doctor.QbitClient, "from_settings", lambda _s: Spy())

    with pytest.raises(RuntimeError):
        await doctor.run(settings, 0)

    assert runner_spy.closed == 1


async def test_a_sandbox_fail_exits_one_and_the_qbittorrent_lines_are_still_printed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = make_settings(tmp_path)
    make_tree(settings)
    fake = FakeRunner()
    fake.unreachable = True
    monkeypatch.setattr(
        doctor,
        "RunnerClient",
        lambda *a, **k: RunnerClient("http://s.test", transport=fake.transport),
    )

    async def fine(_qbit, _settings):
        return [(True, "WebAPI version 2.15.1"), doctor.legacy_note([], _settings)]

    monkeypatch.setattr(doctor, "collect", fine)
    monkeypatch.setattr(doctor.QbitClient, "from_settings", lambda _s: Spy())

    code = await doctor.run(settings, 0)

    out = capsys.readouterr().out
    assert code == 1
    assert "OK   WebAPI version 2.15.1" in out
    assert "FAIL sandbox runner not reachable (unreachable)" in out
    assert "OK   hardlink quarantine -> media works" in out


async def test_no_doctor_line_holds_a_credential_a_key_a_hash_or_a_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = make_settings(tmp_path)
    make_tree(settings)
    fake = FakeRunner()
    monkeypatch.setattr(
        doctor,
        "RunnerClient",
        lambda *a, **k: RunnerClient("http://s.test", transport=fake.transport),
    )

    async def fine(_qbit, _settings):
        rows = [{"hash": HASH, "name": NAME, "category": "Film", "save_path": "/old"}]
        return [doctor.legacy_note(rows, _settings)]

    monkeypatch.setattr(doctor, "collect", fine)
    monkeypatch.setattr(doctor.QbitClient, "from_settings", lambda _s: Spy())

    assert await doctor.run(settings, 0) == 0

    out = capsys.readouterr().out
    for secret in (QBIT_PASS, QBIT_USER, SECRET, PORTAL_PASS_HASH, HASH, NAME, "famiglia-test"):
        assert secret not in out
