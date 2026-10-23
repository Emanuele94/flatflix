"""Real microVMs on generated fixtures, judged by the same rules the backend uses (QUAR-02/03).

Run with the stack up: SANDBOX_TEST=1 uv run --project backend --frozen pytest \
backend/tests/sandbox_real -m sandbox -q -rs
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.quarantine.rules import judge
from app.quarantine.runner_client import ProbeFacts
from tests.sandbox_real.conftest import probe_rel

pytestmark = pytest.mark.sandbox

# The 60 s fixtures fail the real 40-minute minimum on purpose, so the rules get lower limits.
LIMITS = {"min_minutes": 0.5, "min_kbps": 100, "max_kbps": 100000}


def _verdict(fixtures_dir: Path, name: str, body: dict):
    facts = ProbeFacts.from_json(body)
    size = (fixtures_dir / name).stat().st_size
    return facts, judge(Path(name).suffix, facts, size, **LIMITS)


@pytest.mark.parametrize("name", ["good.mkv", "good.mp4", "good.avi"])
def test_a_real_short_clip_passes(fixtures_dir, probe, name):
    http, body = probe(name)
    assert http == 200
    assert body["status"] == "ok", body
    facts, verdict = _verdict(fixtures_dir, name, body)
    assert verdict.passed, (verdict, body)
    assert facts.duration is not None and float(facts.duration) > 0


def test_an_mp4_with_the_moov_atom_last_and_an_odd_size_gets_its_duration(fixtures_dir, probe):
    assert (fixtures_dir / "good.mp4").stat().st_size % 512 != 0
    http, body = probe("good.mp4")
    assert http == 200 and body["status"] == "ok", body
    assert "mov" in body["format"]["format_name"].split(",")
    assert float(body["format"]["duration"]) == pytest.approx(60, abs=2)


def test_an_mp4_named_mkv_is_a_container_mismatch(fixtures_dir, probe):
    http, body = probe("mismatch.mkv")
    assert http == 200 and body["status"] == "ok", body
    facts, verdict = _verdict(fixtures_dir, "mismatch.mkv", body)
    assert "mov" in (facts.format_name or "").split(",")
    assert not verdict.passed and verdict.reason == "container_mismatch"


def test_audio_only_has_no_video_stream(fixtures_dir, probe):
    http, body = probe("audio_only.mkv")
    assert http == 200 and body["status"] == "ok", body
    _, verdict = _verdict(fixtures_dir, "audio_only.mkv", body)
    assert not verdict.passed and verdict.reason == "no_video_stream"


def test_a_truncated_file_fails_the_bitrate_band(fixtures_dir, probe):
    http, body = probe("truncated.mkv")
    assert http == 200 and body["status"] == "ok", body
    _, verdict = _verdict(fixtures_dir, "truncated.mkv", body)
    assert not verdict.passed and verdict.reason == "bitrate_low"


@pytest.mark.parametrize("name", ["fake.mkv", "text.mkv"])
def test_a_renamed_executable_and_a_text_file_fail_to_probe(fixtures_dir, probe, name):
    http, body = probe(name)
    assert http == 200
    assert body["status"] == "probe_failed", body
    _, verdict = _verdict(fixtures_dir, name, body)
    assert not verdict.passed and verdict.reason == "probe_failed"


def test_a_tiny_file_is_too_small_without_booting_a_vm(fixtures_dir, probe):
    http, body = probe("tiny.mkv")
    assert http == 200
    assert body["status"] == "probe_failed" and body["reason"] == "too_small", body


def test_a_path_that_climbs_out_of_the_quarantine_is_refused():
    http, body = probe_rel("../etc/passwd")
    assert http == 400 and body["error"] == "invalid_path", body


def test_a_missing_file_is_not_found():
    http, body = probe_rel(".fx-test/missing.mkv")
    assert http == 404 and body["error"] == "not_found", body
