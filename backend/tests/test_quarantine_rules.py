"""QUAR-03 rules: the tracer (a film's facts through RunnerClient and judge) and the judge itself."""

from app.quarantine.rules import PASS, Verdict, judge
from app.quarantine.runner_client import RunnerClient
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
