"""The outcome store (D-54, D-55, D-77): sidecars that outlive a torrent, and the seven-day purge.

Everything runs against a real folder under `tmp_path`; ages are set with `os.utime`.
"""

import json
import os
import stat
from pathlib import Path

import pytest

from app.quarantine.outcomes import Outcome, OutcomeStore

NOW = 1_700_000_000.0
DAY = 86400
RETENTION = 7 * DAY
ID = "0123456789abcdef"
OTHER_ID = "fedcba9876543210"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "rejected"


@pytest.fixture
def store(root: Path) -> OutcomeStore:
    return OutcomeStore(root)


def outcome(outcome_id: str = ID, **overrides) -> Outcome:
    values = {
        "id": outcome_id,
        "name": "Movie (2020)",
        "type": "film",
        "kind": "rejected",
        "skipped": 1,
        "at": NOW,
    }
    values.update(overrides)
    return Outcome(**values)


def age(path: Path, seconds: float) -> None:
    """Make a path look `seconds` old without following a symlink."""
    stamp = NOW - seconds
    os.utime(path, (stamp, stamp), follow_symlinks=False)


def test_a_written_outcome_reads_back_and_the_sidecar_is_owner_only(
    store: OutcomeStore, root: Path
) -> None:
    store.write(outcome())

    assert store.get(ID) == outcome()
    sidecar = root / f"{ID}.json"
    assert stat.S_IMODE(os.stat(sidecar).st_mode) == 0o600
    assert set(json.loads(sidecar.read_text())) == {"id", "name", "type", "kind", "skipped", "at"}


def test_a_second_write_replaces_the_first_atomically_and_leaves_no_temp_file(
    store: OutcomeStore, root: Path
) -> None:
    store.write(outcome(kind="rejected"))
    store.write(outcome(kind="ready", skipped=0))

    assert store.get(ID) == outcome(kind="ready", skipped=0)
    assert sorted(p.name for p in root.iterdir()) == [f"{ID}.json"]


def test_an_id_that_is_not_sixteen_lower_case_hex_is_refused(store: OutcomeStore) -> None:
    for bad in ("../x", "ABCDEF0123456789", "0123", "0123456789abcdeg", ""):
        with pytest.raises(ValueError):
            store.write(outcome(bad))
        assert store.get(bad) is None
        with pytest.raises(ValueError):
            store.rejected_dir(bad)


def test_rejected_dir_is_the_folder_named_by_the_id(store: OutcomeStore, root: Path) -> None:
    assert store.rejected_dir(ID) == root / ID


def test_load_all_returns_good_outcomes_and_skips_everything_malformed(
    store: OutcomeStore, root: Path, tmp_path: Path
) -> None:
    store.write(outcome(ID))
    store.write(outcome(OTHER_ID, kind="ready", skipped=0))
    (root / "aaaaaaaaaaaaaaaa.json").write_text("{not json")
    good = json.loads((root / f"{ID}.json").read_text())
    (root / "bbbbbbbbbbbbbbbb.json").write_text(
        json.dumps(dict(good, id="bbbbbbbbbbbbbbbb", why="x"))
    )
    missing = {k: v for k, v in good.items() if k != "skipped"}
    (root / "cccccccccccccccc.json").write_text(json.dumps(dict(missing, id="cccccccccccccccc")))
    (root / "not-sixteen-hex.json").write_text(json.dumps(good))
    (root / "dddddddddddddddd.json").mkdir()  # a directory named like a sidecar
    target = tmp_path / "outside.json"
    target.write_text(json.dumps(dict(good, id="eeeeeeeeeeeeeeee")))
    (root / "eeeeeeeeeeeeeeee.json").symlink_to(target)
    (root / "ffffffffffffffff.json").write_text(json.dumps(dict(good, kind="odd")))
    (root / f".{ID}.json.tmp").write_text(json.dumps(good))  # an interrupted write

    loaded = store.load_all()

    assert sorted(item.id for item in loaded) == sorted([ID, OTHER_ID])


def test_load_all_of_a_missing_folder_is_empty_and_never_raises(tmp_path: Path) -> None:
    assert OutcomeStore(tmp_path / "nope").load_all() == []


def test_remove_deletes_the_sidecar_once(store: OutcomeStore, root: Path) -> None:
    store.write(outcome())

    assert store.remove(ID) is True
    assert store.remove(ID) is False
    assert store.get(ID) is None
    assert not (root / f"{ID}.json").exists()


def test_purge_removes_sidecars_and_folders_older_than_the_retention(
    store: OutcomeStore, root: Path
) -> None:
    store.write(outcome(ID, at=NOW - 8 * DAY))
    old_folder = store.rejected_dir(ID)
    (old_folder / "Movie").mkdir(parents=True)
    (old_folder / "Movie" / "movie.mkv").write_bytes(b"x")
    age(old_folder, 8 * DAY)
    store.write(outcome(OTHER_ID, at=NOW - 6 * DAY))
    young_folder = store.rejected_dir(OTHER_ID)
    young_folder.mkdir()
    (young_folder / "a.mkv").write_bytes(b"x")
    age(young_folder, 6 * DAY)

    removed = store.purge(NOW, RETENTION)

    assert removed == 2
    assert sorted(p.name for p in root.iterdir()) == [OTHER_ID, f"{OTHER_ID}.json"]


def test_a_ready_sidecar_is_purged_by_the_visible_window_not_by_the_rejected_retention(
    store: OutcomeStore, root: Path
) -> None:
    """WR-08: a short retention must not hide a Ready row early, and a longer retention must
    not keep one past its window."""
    store.write(outcome(ID, kind="ready", at=NOW - 5 * DAY))
    store.write(outcome(OTHER_ID, kind="rejected", at=NOW - 5 * DAY))

    # retention 3 days, Ready rows visible for 7: only the rejected sidecar goes
    assert store.purge(NOW, 3 * DAY, 7 * DAY) == 1
    assert sorted(p.name for p in root.iterdir()) == [f"{ID}.json"]

    # the Ready row is past its own window now
    assert store.purge(NOW, 3 * DAY, 4 * DAY) == 1
    assert list(root.iterdir()) == []


def test_purge_removes_a_symlink_as_a_link_and_never_follows_it(
    store: OutcomeStore, root: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "precious.txt").write_text("keep")
    root.mkdir()
    (root / "evil").symlink_to(outside)
    (root / "evil.json").symlink_to(outside / "precious.txt")
    inner = root / ID
    inner.mkdir()
    (inner / "link").symlink_to(outside)
    age(inner, 8 * DAY)

    removed = store.purge(NOW, RETENTION)

    assert removed == 3
    assert list(root.iterdir()) == []
    assert (outside / "precious.txt").read_text() == "keep"
    assert [p.name for p in outside.iterdir()] == ["precious.txt"]


def test_purge_removes_stale_stray_files_and_unreadable_sidecars_by_their_mtime(
    store: OutcomeStore, root: Path
) -> None:
    root.mkdir()
    stale_tmp = root / f".{ID}.json.tmp"
    stale_tmp.write_text("x")
    age(stale_tmp, 8 * DAY)
    broken = root / f"{OTHER_ID}.json"
    broken.write_text("{not json")
    age(broken, 8 * DAY)
    fresh = root / "aaaaaaaaaaaaaaaa.json"
    fresh.write_text("{not json")
    age(fresh, 1 * DAY)

    assert store.purge(NOW, RETENTION) == 2
    assert [p.name for p in root.iterdir()] == ["aaaaaaaaaaaaaaaa.json"]


def test_purge_of_a_missing_folder_removes_nothing_and_never_raises(tmp_path: Path) -> None:
    assert OutcomeStore(tmp_path / "nope").purge(NOW, RETENTION) == 0


def test_purge_survives_a_folder_it_cannot_remove(
    store: OutcomeStore, root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = store.rejected_dir(ID)
    folder.mkdir(parents=True)
    age(folder, 8 * DAY)

    def broken(*args, **kwargs):
        raise OSError(13, "Permission denied /secret/path")

    monkeypatch.setattr("app.quarantine.outcomes.shutil.rmtree", broken)

    assert store.purge(NOW, RETENTION) == 0  # logged by class name only, never raised
