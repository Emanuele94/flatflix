"""QUAR-03 rules: the tracer (a film's facts through RunnerClient and judge) and the judge itself."""

import pytest

from app.quarantine.rules import (
    PASS,
    TAG_VERIFIED_PREFIX,
    FileToCheck,
    Verdict,
    files_to_check,
    in_quarantine,
    judge,
    min_minutes_for,
    summary,
    verified_at,
    verified_tag,
)
from app.quarantine.runner_client import ProbeFacts, RunnerClient
from tests.fakerunner import FakeRunner, failed_facts, film_facts

BASE = "http://sandbox.test"
JUDGE_ARGS = {"min_minutes": 40, "min_kbps": 100, "max_kbps": 100_000}


async def test_a_real_films_facts_come_back_through_the_client_and_pass() -> None:
    fake = FakeRunner()
    fake.script("Film/Movie/movie.mkv", film_facts(duration=6000.0))
    client = RunnerClient(BASE, transport=fake.transport)

    facts = await client.probe("Film/Movie/movie.mkv")

    assert facts.status == "ok"
    assert facts.format_name == "matroska,webm"
    video = [s for s in facts.streams if s.codec_type == "video"]
    assert [s.codec_name for s in video] == ["h264"]
    assert fake.calls == ["Film/Movie/movie.mkv"]
    assert fake.bodies == [{"path": "Film/Movie/movie.mkv"}]
    # about 5.3 Mbps over 100 minutes
    assert judge(".mkv", facts, 4_000_000_000, **JUDGE_ARGS) == PASS
    await client.aclose()


async def test_a_renamed_executable_fails_as_probe_failed() -> None:
    fake = FakeRunner()
    fake.script("Film/Movie/fake.mkv", failed_facts("probe_failed"))
    client = RunnerClient(BASE, transport=fake.transport)

    facts = await client.probe("Film/Movie/fake.mkv")

    assert judge(".mkv", facts, 1_669_418, **JUDGE_ARGS) == Verdict(False, "probe_failed")
    await client.aclose()


# --- Task 2: every rule of QUAR-03, which files to check, the verified tag -------------------------

MP4_FAMILY = "mov,mp4,m4a,3gp,3g2,mj2"
FIXTURE_ARGS = {"min_minutes": 0.5, "min_kbps": 100, "max_kbps": 100_000}


def facts_of(**kwargs) -> ProbeFacts:
    return ProbeFacts.from_json(film_facts(**kwargs))


def audio_only_facts() -> ProbeFacts:
    body = film_facts(duration=60.023, size=1_600_000)
    body["streams"] = [{"index": 0, "codec_type": "audio", "codec_name": "mp3"}]
    return ProbeFacts.from_json(body)


@pytest.mark.parametrize(
    ("extension", "facts", "size", "expected"),
    [
        (".mkv", facts_of(duration=60.023, size=1_600_000), 1_600_000, PASS),
        (
            ".mp4",
            facts_of(duration=60.023152, size=1_669_418, format_name=MP4_FAMILY),
            1_669_418,
            PASS,
        ),
        (
            ".avi",
            facts_of(duration=60.0, size=1_600_000, format_name="avi", codec="mpeg4"),
            1_600_000,
            PASS,
        ),
        (
            ".mkv",
            facts_of(duration=60.023, size=1_669_418, format_name=MP4_FAMILY),
            1_669_418,
            Verdict(False, "container_mismatch"),
        ),
        (".mkv", audio_only_facts(), 1_600_000, Verdict(False, "no_video_stream")),
        (
            ".mkv",
            facts_of(duration=60.023, size=204_800),
            204_800,
            Verdict(False, "bitrate_low"),
        ),
        (
            ".mkv",
            ProbeFacts.from_json(failed_facts("probe_failed")),
            1_669_418,
            Verdict(False, "probe_failed"),
        ),
        (
            ".mkv",
            ProbeFacts.from_json(failed_facts("timeout")),
            1_669_418,
            Verdict(False, "timeout"),
        ),
    ],
    ids=[
        "good.mkv",
        "good.mp4",
        "good.avi",
        "mismatch.mkv",
        "audio_only.mkv",
        "truncated.mkv",
        "fake.mkv",
        "timeout",
    ],
)
def test_the_research_fixtures_reach_the_decided_verdicts(extension, facts, size, expected) -> None:
    assert judge(extension, facts, size, **FIXTURE_ARGS) == expected


def at_kbps(kbps: int, duration: float = 2400.0) -> int:
    """Bytes that make exactly `kbps` over `duration` seconds."""
    return int(kbps * 1000 * duration / 8)


@pytest.mark.parametrize(
    ("duration", "size", "expected"),
    [
        (2400.0, at_kbps(1000), PASS),
        (2399.9, at_kbps(1000), Verdict(False, "too_short")),
        (2400.0, at_kbps(100), PASS),
        (2400.0, at_kbps(100) - 1, Verdict(False, "bitrate_low")),
        (2400.0, at_kbps(100_000), PASS),
        (2400.0, at_kbps(100_000) + 1, Verdict(False, "bitrate_high")),
    ],
    ids=["min-exact", "min-below", "kbps-min", "kbps-below", "kbps-max", "bitrate_high"],
)
def test_boundaries_are_inclusive(duration, size, expected) -> None:
    facts = facts_of(duration=duration, size=size)
    assert judge(".mkv", facts, size, **JUDGE_ARGS) == expected


@pytest.mark.parametrize(
    ("extension", "format_name", "expected"),
    [
        (".m4v", MP4_FAMILY, PASS),
        (".mp4", "mp4", PASS),
        (".avi", "matroska,webm", Verdict(False, "container_mismatch")),
        (".MKV", "matroska,webm", PASS),
        (".webm", "matroska,webm", Verdict(False, "unknown_extension")),
        (".mkv", None, Verdict(False, "container_mismatch")),
    ],
)
def test_extension_and_container_family(extension, format_name, expected) -> None:
    facts = facts_of(format_name=format_name or "")
    if format_name is None:
        body = film_facts()
        body["format"]["format_name"] = None
        facts = ProbeFacts.from_json(body)
    assert judge(extension, facts, 4_000_000_000, **JUDGE_ARGS) == expected


def facts_with_streams(streams: list[dict]) -> ProbeFacts:
    body = film_facts()
    body["streams"] = streams
    return ProbeFacts.from_json(body)


def video(codec: str | None = "h264", attached_pic: bool = False, index: int = 0) -> dict:
    return {
        "index": index,
        "codec_type": "video",
        "codec_name": codec,
        "attached_pic": attached_pic,
    }


@pytest.mark.parametrize(
    ("streams", "expected"),
    [
        ([video(attached_pic=True)], Verdict(False, "no_video_stream")),
        ([video(codec=None)], Verdict(False, "no_video_stream")),
        ([video(codec="")], Verdict(False, "no_video_stream")),
        ([video(codec="unknown")], Verdict(False, "no_video_stream")),
        ([video(codec="none")], Verdict(False, "no_video_stream")),
        ([video(codec="mjpeg", attached_pic=True), video(index=1)], PASS),
        ([], Verdict(False, "no_video_stream")),
    ],
)
def test_a_video_stream_must_be_real_and_not_cover_art(streams, expected) -> None:
    assert judge(".mkv", facts_with_streams(streams), 4_000_000_000, **JUDGE_ARGS) == expected


@pytest.mark.parametrize("duration", [None, "N/A", "nan", "inf", "0", "-5"])
def test_an_unusable_duration_is_no_duration(duration) -> None:
    body = film_facts()
    body["format"]["duration"] = duration
    facts = ProbeFacts.from_json(body)
    assert judge(".mkv", facts, 4_000_000_000, **JUDGE_ARGS) == Verdict(False, "no_duration")


def test_judge_is_pure_and_independent_of_the_order_of_a_packs_files() -> None:
    cases = [
        (".mkv", facts_of(duration=6000.0 + i * 10), at_kbps(5000, 6000.0 + i * 10))
        for i in range(6)
    ] + [
        (".mkv", ProbeFacts.from_json(failed_facts()), 1_000_000),
        (".mkv", facts_of(duration=60.0), 10),
    ]
    forwards = [judge(ext, f, size, **JUDGE_ARGS) for ext, f, size in cases]
    backwards = [judge(ext, f, size, **JUDGE_ARGS) for ext, f, size in reversed(cases)]
    assert forwards == list(reversed(backwards))
    assert forwards == [judge(ext, f, size, **JUDGE_ARGS) for ext, f, size in cases]


def test_summary_names_format_codec_and_whole_seconds() -> None:
    assert summary(facts_of()) == {"format": "matroska", "codec": "h264", "duration": "6000"}


def test_summary_says_none_for_missing_parts() -> None:
    facts = ProbeFacts.from_json(failed_facts())
    assert summary(facts) == {"format": "none", "codec": "none", "duration": "none"}


def test_summary_tokens_are_safe_to_log() -> None:
    body = film_facts(format_name="evil name\nx=1,webm", codec="h264 \x1b[31m")
    assert summary(ProbeFacts.from_json(body))["format"] == "none"
    assert summary(ProbeFacts.from_json(body))["codec"] == "none"


def row(index, name, size=1_000_000_000, priority=1, progress=1) -> dict:
    return {"index": index, "name": name, "size": size, "priority": priority, "progress": progress}


def test_a_film_pack_keeps_the_main_video_extras_and_subtitles() -> None:
    rows = [
        row(0, "Movie/movie.mkv", 4_000_000_000),
        row(1, "Movie/extras/making-of.mp4", 300_000_000),
        row(2, "Movie/Sample/movie-sample.mkv"),
        row(3, "Movie/movie.srt", 50_000),
        row(4, "Movie/.abc.parts"),
        row(5, "Movie/movie.nfo"),
        row(6, "Movie/other.mkv", priority=0),
        row(7, "Movie/part.mkv", progress=0.5),
    ]
    assert files_to_check(rows, "film") == [
        FileToCheck(0, "Movie/movie.mkv", 4_000_000_000, "video", True),
        FileToCheck(1, "Movie/extras/making-of.mp4", 300_000_000, "video", False),
        FileToCheck(3, "Movie/movie.srt", 50_000, "subtitle", False),
    ]


def test_on_a_size_tie_the_lowest_index_is_the_main_video() -> None:
    rows = [row(5, "M/b.mkv"), row(2, "M/a.mkv")]
    assert files_to_check(rows, "film") == [
        FileToCheck(2, "M/a.mkv", 1_000_000_000, "video", True),
        FileToCheck(5, "M/b.mkv", 1_000_000_000, "video", False),
    ]


def test_every_episode_of_a_series_is_main() -> None:
    rows = [row(i, f"Show/Season 01/Show S01E0{i + 1}.mkv", 500_000_000 + i) for i in range(3)]
    result = files_to_check(rows, "serie")
    assert [f.is_main for f in result] == [True, True, True]
    assert [f.index for f in result] == [0, 1, 2]


def test_a_series_sample_is_skipped_too() -> None:
    rows = [row(0, "Show/S01E01.mkv"), row(1, "Show/Sample/s01e01-sample.mkv")]
    assert [f.index for f in files_to_check(rows, "serie")] == [0]


@pytest.mark.parametrize(
    "bad",
    [
        row(1, ".hidden/ep.mkv"),
        row(1, "Show/.ep.mkv"),
        row(1, "Show/../ep.mkv"),
        row(1, "Show/ep.mkv", progress="x"),
        row(1, "Show/ep.mkv", priority="high"),
        row(1, "Show/ep.mkv", progress=None),
        row(1, "Show/ep.mkv", progress=float("nan")),
        {"index": 1, "name": "Show/ep.mkv"},
    ],
)
def test_unsafe_or_unreadable_rows_are_skipped(bad) -> None:
    assert files_to_check([row(0, "Show/ep0.mkv"), bad], "serie") == [
        FileToCheck(0, "Show/ep0.mkv", 1_000_000_000, "video", True)
    ]


def test_files_to_check_is_pure_and_independent_of_row_order() -> None:
    rows = [row(i, f"Show/Show S01E{i:02}.mkv", 400_000_000 + i) for i in range(6)]
    assert files_to_check(rows, "serie") == files_to_check(list(reversed(rows)), "serie")
    assert files_to_check(rows, "serie") == files_to_check(rows, "serie")


@pytest.mark.parametrize(
    ("content_type", "is_main", "expected"),
    [("film", True, 40), ("film", False, 0), ("serie", True, 10), ("serie", False, 10)],
)
def test_min_minutes_per_kind_of_file(content_type, is_main, expected) -> None:
    got = min_minutes_for(content_type, is_main, film_minutes=40, episode_minutes=10)
    assert got == expected


def test_the_verified_tag_round_trips() -> None:
    assert verified_tag(1700000000.9) == "fx-ok-1700000000"
    assert TAG_VERIFIED_PREFIX == "fx-ok-"
    assert verified_at(["fx", "fx-ok-1700000000"]) == 1700000000.0
    assert verified_at(["fx-ok-abc"]) is None
    assert verified_at(["fx-ok-"]) is None
    assert verified_at([]) is None


@pytest.mark.parametrize(
    ("save_path", "expected"),
    [
        ("/data/quarantine/Film", True),
        ("/data/quarantine/Film/", True),
        ("/data/quarantine", False),
        ("/data/quarantine/", False),
        ("/data/quarantine-old/Film", False),
        ("/data/media/Film", False),
        ("/data/quarantine/../media", False),
        ("quarantine/Film", False),
    ],
)
def test_in_quarantine_is_strictly_inside_the_root(save_path, expected) -> None:
    assert in_quarantine(save_path, "/data/quarantine") is expected
