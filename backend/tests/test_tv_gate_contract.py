"""Contract tests for the TV gate helper (COMPAT-01 to 03, D-85 to D-89, D-99).

`scripts/tv_gate.py`, `scripts/make_compat_clips.py` and `scripts/jellyfin_setup.py` are standalone
standard-library scripts, so they are loaded by path. Only pure parts are exercised here: no request
is made and nothing under the real jellyfin folder is touched.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def load(name: str, filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses looks its own module up here
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tg() -> ModuleType:
    return load("flatflix_tg_tv_gate", "tv_gate.py")


@pytest.fixture(scope="module")
def mc() -> ModuleType:
    return load("flatflix_tg_make_compat_clips", "make_compat_clips.py")


@pytest.fixture(scope="module")
def js() -> ModuleType:
    return load("flatflix_tg_jellyfin_setup", "jellyfin_setup.py")


# --- helpers ----------------------------------------------------------------------------


def info(video_direct: bool = True, audio_direct: bool = True, reasons=None) -> dict:
    return {
        "IsVideoDirect": video_direct,
        "IsAudioDirect": audio_direct,
        "VideoCodec": "h264",
        "AudioCodec": "aac",
        "Container": "ts",
        "Width": 1920,
        "Height": 1080,
        "Bitrate": 8_000_000,
        "TranscodeReasons": list(reasons or []),
    }


def session(
    name: str | None = "A01 MKV H264 AAC",
    *,
    sid: str = "s1",
    item: str = "0123456789abcdef0123456789abcdef",
    client: str = "Jellyfin Web",
    method: str = "Transcode",
    subtitle=None,
    transcoding=None,
) -> dict:
    out: dict = {
        "Id": sid,
        "Client": client,
        "ApplicationVersion": "12.3.0",
        "DeviceId": "secret-device-id",
        "DeviceName": "secret-device-name",
        "RemoteEndPoint": "192.168.1.50",
        "UserName": "household",
        "PlayState": {"PlayMethod": method, "SubtitleStreamIndex": subtitle},
        "TranscodingInfo": transcoding,
    }
    if name is not None:
        out["NowPlayingItem"] = {"Id": item, "Name": name}
    return out


def fake_manifest(mc: ModuleType, na: dict | None = None) -> dict:
    return {r.id: {"file": f"{r.id}.mkv", "na": (na or {}).get(r.id), "note": None} for r in mc.CATALOGUE}


# --- pure helpers (Task 1) ----------------------------------------------------------------


def test_row_id_of_takes_the_first_catalogue_shaped_token(tg: ModuleType) -> None:
    assert tg.row_id_of("A01 MKV H264 AAC") == "A01"
    assert tg.row_id_of("A01 MKV") == "A01"
    assert tg.row_id_of("S04 MP4 H264 AAC MOVTEXT") == "S04"
    assert tg.row_id_of("Big Buck Bunny") is None
    assert tg.row_id_of("") is None
    assert tg.row_id_of(None) is None


def test_log_type_of_reads_the_type_of_an_ffmpeg_log_name(tg: ModuleType) -> None:
    assert tg.log_type_of("FFmpeg.Remux-2026-10-26_10-00-00_0123abcd_9f.log") == "Remux"
    assert tg.log_type_of("FFmpeg.DirectStream-2026-10-26_10-00-00_0123abcd_9f.log") == "DirectStream"
    assert tg.log_type_of("FFmpeg.Transcode-2026-10-26_10-00-00_0123abcd_9f.log") == "Transcode"
    assert tg.log_type_of("log_20261025.log") is None
    assert tg.log_type_of("FFmpeg.Other-2026-10-26_10-00-00_0123abcd_9f.log") is None


@pytest.mark.parametrize(
    ("play_method", "ti", "logs", "expected"),
    [
        ("Transcode", None, ["Transcode"], "Video transcode"),
        ("Transcode", None, ["DirectStream"], "Audio transcode"),
        ("Transcode", None, ["Remux"], "Remux"),
        ("Transcode", info(video_direct=False), [], "Video transcode"),
        ("Transcode", info(video_direct=True, audio_direct=False), [], "Audio transcode"),
        ("Transcode", info(), [], "Remux"),
        ("DirectPlay", None, [], "Direct play"),
        ("DirectStream", None, [], "not tested"),
        (None, None, [], "not tested"),
    ],
)
def test_classify_follows_the_research_mapping(tg: ModuleType, play_method, ti, logs, expected) -> None:
    assert tg.classify(play_method, ti, logs) == expected


def test_a_log_decides_before_the_session_and_the_worst_log_wins(tg: ModuleType) -> None:
    assert tg.classify("DirectPlay", None, ["Remux", "Transcode"]) == "Video transcode"
    assert tg.classify("Transcode", info(video_direct=False), ["Remux"]) == "Remux"


def test_worst_orders_the_four_methods(tg: ModuleType) -> None:
    assert tg.worst(["Remux", "Video transcode", "Direct play"]) == "Video transcode"
    assert tg.worst(["Direct play", "Remux"]) == "Remux"
    assert tg.worst(["Remux", "Audio transcode"]) == "Audio transcode"
    assert tg.worst(["Direct play"]) == "Direct play"
    assert tg.worst([]) == "not tested"
    assert tg.worst(["not tested", "Remux"]) == "Remux"
    assert tg.worst(["not tested"]) == "not tested"


def test_signals_disagree_when_the_log_and_the_session_name_different_methods(tg: ModuleType) -> None:
    assert tg.signals_disagree(["Remux"], info(video_direct=False)) is True
    assert tg.signals_disagree(["Transcode"], info()) is True
    assert tg.signals_disagree(["DirectStream"], info(audio_direct=False)) is False
    assert tg.signals_disagree(["Remux"], info()) is False
    assert tg.signals_disagree([], info()) is False
    assert tg.signals_disagree(["Remux"], None) is False


# --- the tracker (Task 1) -----------------------------------------------------------------


def test_the_tracker_keeps_the_last_transcoding_info_when_later_polls_have_none(tg: ModuleType) -> None:
    tracker = tg.Tracker()
    first = info(video_direct=True, audio_direct=False, reasons=["AudioCodecNotSupported"])

    assert tracker.observe([session(transcoding=first)], 1.0) == []
    assert tracker.observe([session(transcoding=None)], 2.0) == []
    finished = tracker.observe([], 3.0)

    assert len(finished) == 1
    entry = finished[0]
    assert entry["row"] == "A01"
    assert entry["transcoding"]["IsAudioDirect"] is False
    assert entry["reasons"] == ["AudioCodecNotSupported"]
    assert entry["start"] == 1.0


def test_the_tracker_collects_every_transcode_reason_once(tg: ModuleType) -> None:
    tracker = tg.Tracker()
    tracker.observe([session(transcoding=info(reasons=["A", "B"]))], 1.0)
    tracker.observe([session(transcoding=info(reasons=["B", "C"]))], 2.0)

    (entry,) = tracker.observe([], 3.0)

    assert entry["reasons"] == ["A", "B", "C"]


def test_the_tracker_reports_a_session_finished_when_the_item_changes(tg: ModuleType) -> None:
    tracker = tg.Tracker()
    tracker.observe([session("A01 MKV")], 1.0)

    finished = tracker.observe([session("A02 MKV", item="f" * 32)], 2.0)

    assert [f["row"] for f in finished] == ["A01"]


def test_the_tracker_ignores_flatflix_clients_unless_asked(tg: ModuleType) -> None:
    mine = session(client="flatflix-setup")

    watching = tg.Tracker()
    watching.observe([mine], 1.0)
    assert watching.observe([], 2.0) == []

    selftest = tg.Tracker(ignore_prefix=None)
    selftest.observe([mine], 1.0)
    assert len(selftest.observe([], 2.0)) == 1


def test_the_tracker_ignores_items_without_a_row_id_and_idle_sessions(tg: ModuleType) -> None:
    tracker = tg.Tracker()
    tracker.observe([session("Big Buck Bunny"), session(None, sid="s2")], 1.0)

    assert tracker.observe([], 2.0) == []


def test_the_tracker_notes_that_subtitles_were_on_and_keeps_client_and_version_only(tg: ModuleType) -> None:
    tracker = tg.Tracker()
    tracker.observe([session("S02 MKV", subtitle=None)], 1.0)
    tracker.observe([session("S02 MKV", subtitle=2)], 2.0)
    (entry,) = tracker.observe([], 3.0)

    assert entry["subtitles_on"] is True
    assert entry["client"] == "Jellyfin Web"
    assert entry["version"] == "12.3.0"
    text = repr(entry)
    for secret in ("secret-device", "192.168", "household", "RemoteEndPoint", "DeviceId"):
        assert secret not in text


def test_finish_all_closes_what_is_still_playing(tg: ModuleType) -> None:
    tracker = tg.Tracker()
    tracker.observe([session()], 1.0)

    assert [f["row"] for f in tracker.finish_all()] == ["A01"]
    assert tracker.finish_all() == []


# --- the matrix (Task 1) --------------------------------------------------------------------


def test_render_matrix_of_nothing_has_five_groups_and_only_not_tested(tg: ModuleType, mc: ModuleType) -> None:
    text = tg.render_matrix({}, {})
    headings = [line for line in text.splitlines() if line.startswith("## ")]

    assert headings == ["## " + heading for _, heading, _ in mc.GROUPS]
    assert text.count(tg.HEADER) == 5
    for r in mc.CATALOGUE:
        line = next(ln for ln in text.splitlines() if ln.startswith(f"| {r.id} |"))
        cells = [c.strip() for c in line.strip("|").split("|")]
        assert len(cells) == 9
        assert cells[6] == "not tested"
        assert cells[8] == "not tested"
        assert all(cells)


def test_the_header_is_the_nine_ui_spec_columns(tg: ModuleType) -> None:
    assert tg.HEADER == (
        "| ID | Container | Video | Audio | Subtitles | Resolution | Method | Reason | Picture and sound OK |"
    )


def test_a_clip_without_audio_prints_none_not_not_tested(tg: ModuleType) -> None:
    text = tg.render_matrix({}, {})
    line = next(ln for ln in text.splitlines() if ln.startswith("| K01 |"))

    assert line.startswith("| K01 | MP4 | HEVC 10-bit HDR10 | none | none | 2160p | not tested |")


def test_the_remux_row_of_a01_renders_the_method_and_its_reasons(tg: ModuleType, mc: ModuleType) -> None:
    results = {
        "A01": [
            {
                "method": "Remux",
                "reasons": ["ContainerNotSupported"],
                "flag": "",
                "ok": None,
                "subtitles_on": False,
            }
        ]
    }

    text = tg.render_matrix(results, fake_manifest(mc))

    assert "| A01 | MKV | H.264 | AAC | none | 1080p | Remux | ContainerNotSupported | not tested |" in text


# --- the device parameter (Task 1) ------------------------------------------------------------


def test_auth_header_can_sign_in_as_its_own_device(js: ModuleType) -> None:
    header = js.auth_header(None, device="flatflix-tv-gate")

    assert 'Device="flatflix-tv-gate"' in header
    assert 'DeviceId="flatflix-tv-gate"' in header
    assert 'Client="flatflix-setup"' in header
    assert "Token" not in header


def test_auth_header_without_a_device_is_unchanged(js: ModuleType) -> None:
    header = js.auth_header(None)

    assert 'Device="flatflix-setup"' in header
    assert 'DeviceId="flatflix-setup"' in header


def test_the_api_passes_its_device_to_the_header(js: ModuleType) -> None:
    assert js.Api("http://x", None, device="d").device == "d"
    assert js.Api("http://x").device == js.CLIENT
