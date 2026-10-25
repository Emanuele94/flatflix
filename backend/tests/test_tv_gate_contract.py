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
# Built from numbers so no private address is spelled out in a tracked file (repo hygiene test).
LAN_ADDRESS = f"{192}.{168}.{1}.{50}"


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
        "RemoteEndPoint": LAN_ADDRESS,
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
    for secret in ("secret-device", LAN_ADDRESS, "household", "RemoteEndPoint", "DeviceId"):
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


# --- Task 2: profiles, results, verdict candidate ---------------------------------------------


def played(method: str, ok: str | None = "yes", *, reasons=None, subtitles_on: bool = False, flag: str = "") -> dict:
    return {
        "method": method,
        "reasons": list(reasons or []),
        "flag": flag,
        "ok": ok,
        "subtitles_on": subtitles_on,
    }


def all_gating_ok(mc: ModuleType, method: str = "Remux") -> dict:
    out = {}
    for r in mc.CATALOGUE:
        if r.gating:
            out[r.id] = [played(method, "yes", subtitles_on=r.group in ("subs", "pgs"))]
    return out


def test_expected_method_maps_the_four_profiles(tg: ModuleType) -> None:
    assert tg.EXPECTED_METHOD == {
        "remux": "Remux",
        "audio": "Audio transcode",
        "video": "Video transcode",
        "direct": "Direct play",
    }


def test_the_audio_profile_forbids_audio_copy_and_the_video_profile_forbids_video_copy(tg: ModuleType) -> None:
    audio = tg.profile_body("audio")
    video = tg.profile_body("video")
    remux = tg.profile_body("remux")

    assert audio["AllowAudioStreamCopy"] is False and audio["AllowVideoStreamCopy"] is True
    assert video["AllowVideoStreamCopy"] is False
    assert remux["AllowAudioStreamCopy"] is True and remux["AllowVideoStreamCopy"] is True
    for body in (audio, video, remux):
        assert body["EnableDirectPlay"] is False
        assert body["DeviceProfile"]["DirectPlayProfiles"] == []
        assert body["DeviceProfile"]["TranscodingProfiles"][0]["Protocol"] == "hls"


def test_the_direct_profile_allows_direct_play_of_one_mkv_profile(tg: ModuleType) -> None:
    body = tg.profile_body("direct")

    assert body["EnableDirectPlay"] is True
    assert body["DeviceProfile"]["DirectPlayProfiles"] == [
        {"Container": "mkv", "Type": "Video", "VideoCodec": "h264", "AudioCodec": "aac"}
    ]


def test_finalize_adds_the_evidence_and_flags_disagreement(tg: ModuleType) -> None:
    entry = {"play_method": "Transcode", "transcoding": info(video_direct=False), "reasons": []}

    done = tg.finalize(dict(entry), ["Remux"])

    assert done["method"] == "Remux"
    assert done["log_types"] == ["Remux"]
    assert done["flag"] == "[signals disagree: log Remux, session IsVideoDirect=False]"
    assert done["ok"] is None


def test_finalize_without_a_flag_when_the_signals_agree(tg: ModuleType) -> None:
    done = tg.finalize({"play_method": "Transcode", "transcoding": info(), "reasons": []}, ["Remux"])

    assert done["flag"] == ""


def test_the_verdict_is_go_when_every_gating_row_passes(tg: ModuleType, mc: ModuleType) -> None:
    assert tg.verdict_of(all_gating_ok(mc), {}) == ("GO", [])
    assert tg.verdict_of(all_gating_ok(mc, "Audio transcode"), {}) == ("GO", [])
    assert tg.verdict_of(all_gating_ok(mc, "Direct play"), {}) == ("GO", [])


def test_a_video_transcode_or_a_no_answer_fails_the_row(tg: ModuleType, mc: ModuleType) -> None:
    results = all_gating_ok(mc)
    results["A04"] = [played("Video transcode", "yes")]
    results["A16"] = [played("Remux", "no")]

    assert tg.verdict_of(results, {}) == ("NO-GO-OR-CONDITIONS", ["A04", "A16"])


def test_a_gating_row_not_tested_makes_the_verdict_incomplete(tg: ModuleType, mc: ModuleType) -> None:
    results = all_gating_ok(mc)
    del results["A07"]

    assert tg.verdict_of(results, {}) == ("INCOMPLETE", ["A07"])


def test_a_played_row_without_an_answer_is_still_incomplete(tg: ModuleType, mc: ModuleType) -> None:
    results = all_gating_ok(mc)
    results["A07"] = [played("Remux", None)]

    assert tg.verdict_of(results, {}) == ("INCOMPLETE", ["A07"])


def test_with_nothing_played_every_gating_row_is_missing(tg: ModuleType, mc: ModuleType) -> None:
    headline, ids = tg.verdict_of({}, {})

    assert headline == "INCOMPLETE"
    assert ids == [r.id for r in mc.CATALOGUE if r.gating]


def test_information_rows_and_na_gating_rows_never_change_the_outcome(tg: ModuleType, mc: ModuleType) -> None:
    results = all_gating_ok(mc)
    results["A24"] = []
    for r in mc.CATALOGUE:
        if not r.gating:
            results[r.id] = [played("Video transcode", "no")]

    manifest = fake_manifest(mc, na={"A24": "n/a — muxer refused"})

    assert tg.verdict_of(results, manifest) == ("GO", [])


def test_the_transcoding_line_says_never_or_names_the_rows(tg: ModuleType, mc: ModuleType) -> None:
    assert tg.transcoding_line(all_gating_ok(mc)) == "1080p content needed video transcoding: never"

    results = all_gating_ok(mc)
    results["A16"] = [played("Video transcode")]
    results["A04"] = [played("Video transcode")]
    results["K01"] = [played("Video transcode")]  # 2160p: not counted

    assert tg.transcoding_line(results) == "1080p content needed video transcoding: for rows A04, A16"


def test_verdict_lines_print_the_candidate_and_the_transcoding_line(tg: ModuleType, mc: ModuleType) -> None:
    go = tg.verdict_lines(all_gating_ok(mc), {})
    assert go == ["CANDIDATE GO", "1080p content needed video transcoding: never"]

    results = all_gating_ok(mc)
    results["A04"] = [played("Video transcode")]
    assert tg.verdict_lines(results, {})[0] == (
        "CANDIDATE NO-GO or GO with conditions; failing rows: A04"
    )

    assert tg.verdict_lines({}, {})[0].startswith("INCOMPLETE rows not tested: A01, A02")


def test_a_subtitle_row_played_with_subtitles_off_stays_not_tested(tg: ModuleType, mc: ModuleType) -> None:
    results = {"S01": [played("Remux", "yes", subtitles_on=False)]}

    text = tg.render_matrix(results, fake_manifest(mc))
    line = next(ln for ln in text.splitlines() if ln.startswith("| S01 |"))

    assert "| not tested | subtitles were off | not tested |" in line


def test_a_subtitle_row_played_with_subtitles_on_counts(tg: ModuleType, mc: ModuleType) -> None:
    results = {"S01": [played("Remux", "yes", subtitles_on=False), played("Audio transcode", "yes", subtitles_on=True)]}

    line = next(ln for ln in tg.render_matrix(results, {}).splitlines() if ln.startswith("| S01 |"))

    assert "| Audio transcode |" in line


def test_two_plays_of_one_clip_merge_into_one_row_with_the_worst_method(tg: ModuleType, mc: ModuleType) -> None:
    results = {
        "A02": [
            played("Remux", "yes", reasons=["ContainerNotSupported"]),
            played("Video transcode", "no", reasons=["VideoCodecNotSupported", "ContainerNotSupported"]),
        ]
    }

    text = tg.render_matrix(results, {})
    rows = [ln for ln in text.splitlines() if ln.startswith("| A02 |")]

    assert len(rows) == 1
    assert rows[0].endswith("| Video transcode | ContainerNotSupported, VideoCodecNotSupported | no |")


def test_two_clips_that_differ_only_in_audio_are_two_rows(tg: ModuleType) -> None:
    text = tg.render_matrix({}, {})
    first = next(ln for ln in text.splitlines() if ln.startswith("| A01 |"))
    second = next(ln for ln in text.splitlines() if ln.startswith("| A02 |"))

    assert "| AAC |" in first and "| AC3 |" in second
    assert first.split("|")[2:4] == second.split("|")[2:4]


def test_the_last_answer_given_wins(tg: ModuleType) -> None:
    results = {"A01": [played("Remux", "no"), played("Remux", None), played("Remux", "yes")]}

    line = next(ln for ln in tg.render_matrix(results, {}).splitlines() if ln.startswith("| A01 |"))

    assert line.endswith("| yes |")


def test_rows_render_in_catalogue_order_whatever_the_play_order(tg: ModuleType, mc: ModuleType) -> None:
    forward = {r.id: [played("Remux")] for r in mc.CATALOGUE}
    backward = dict(reversed(list(forward.items())))

    assert tg.render_matrix(forward, {}) == tg.render_matrix(backward, {})
    ids = [ln.split("|")[1].strip() for ln in tg.render_matrix(forward, {}).splitlines() if ln.startswith("| ") and "---" not in ln and "| ID |" not in ln]
    assert ids == [r.id for r in mc.CATALOGUE]


def test_rendering_twice_gives_identical_text(tg: ModuleType, mc: ModuleType) -> None:
    results = {"A03": [played("Audio transcode", "yes", reasons=["AudioCodecNotSupported"])]}
    manifest = fake_manifest(mc)

    assert tg.render_matrix(results, manifest) == tg.render_matrix(results, manifest)


def test_results_for_an_unknown_row_are_not_rendered(tg: ModuleType) -> None:
    text = tg.render_matrix({"Z99": [played("Remux")]}, {})

    assert "Z99" not in text


def test_a_manifest_na_row_renders_its_reason_as_the_method(tg: ModuleType, mc: ModuleType) -> None:
    manifest = fake_manifest(mc, na={"A24": "n/a — muxer refused DTS in MP4"})

    line = next(ln for ln in tg.render_matrix({}, manifest).splitlines() if ln.startswith("| A24 |"))

    assert "| n/a — muxer refused DTS in MP4 | - | not tested |" in line


def test_the_pgs_row_keeps_its_decided_reason_and_the_burn_in_line_is_not_tested(tg: ModuleType) -> None:
    text = tg.render_matrix({}, {})
    line = next(ln for ln in text.splitlines() if ln.startswith("| P01 |"))

    assert "no PGS encoder in ffmpeg (D-99)" in line
    assert "burn-in forced: not tested" in text.splitlines()


def test_a_disagreement_flag_lands_in_the_reason_cell(tg: ModuleType) -> None:
    flag = "[signals disagree: log Remux, session IsVideoDirect=False]"
    results = {"A01": [played("Remux", "yes", reasons=["ContainerNotSupported"], flag=flag)]}

    line = next(ln for ln in tg.render_matrix(results, {}).splitlines() if ln.startswith("| A01 |"))

    assert f"ContainerNotSupported {flag}" in line


def test_an_entry_never_carries_device_data_or_a_url(tg: ModuleType) -> None:
    dirty = {
        "row": "A01",
        "DeviceId": "x",
        "DeviceName": "y",
        "RemoteEndPoint": LAN_ADDRESS,
        "UserName": "household",
        "client": "http://leak.example/?ApiKey=t",
        "version": "12.3.0",
        "transcoding": {**info(), "SomeUrl": "http://x"},
        "reasons": ["A"],
    }

    clean = tg.clean_entry(dirty)

    assert set(clean) <= set(tg.ENTRY_KEYS)
    assert "client" not in clean
    assert "SomeUrl" not in clean["transcoding"]
    assert "http" not in repr(clean)


def test_the_store_saves_and_loads_rows_and_forgets(tg: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "tv-gate" / "results.json"
    store = tg.ResultStore(path)
    store.add("A01", {"row": "A01", "method": "Remux", "DeviceId": "x"})
    store.add("A01", {"row": "A01", "method": "Audio transcode"})
    store.save()

    again = tg.ResultStore(path)
    assert [e["method"] for e in again.rows()["A01"]] == ["Remux", "Audio transcode"]
    assert "DeviceId" not in path.read_text()
    assert again.forget("A01") is True and again.forget("A01") is False
    assert again.rows() == {}


def test_a_missing_or_broken_results_file_reads_as_empty(tg: ModuleType, tmp_path: Path) -> None:
    assert tg.ResultStore(tmp_path / "none.json").rows() == {}
    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    assert tg.ResultStore(broken).rows() == {}


def test_save_leaves_the_previous_file_intact_when_the_replace_fails(
    tg: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "results.json"
    first = tg.ResultStore(path)
    first.add("A01", {"row": "A01", "method": "Remux"})
    first.save()
    before = path.read_text()

    second = tg.ResultStore(path)
    second.add("A02", {"row": "A02", "method": "Remux"})

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(tg.os, "replace", boom)
    with pytest.raises(OSError):
        second.save()

    assert path.read_text() == before
    assert [p.name for p in tmp_path.iterdir()] == ["results.json"]


def test_save_refuses_data_it_cannot_serialise_and_keeps_the_old_file(tg: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "results.json"
    store = tg.ResultStore(path)
    store.add("A01", {"row": "A01"})
    store.save()
    before = path.read_text()
    store.data["A02"] = [{"row": object()}]

    with pytest.raises(TypeError):
        store.save()

    assert path.read_text() == before
    assert [p.name for p in tmp_path.iterdir()] == ["results.json"]


# --- Task 3: the committed document and its validator --------------------------------------------

DOC_PATH = Path(__file__).resolve().parents[2] / "docs" / "tv-compatibility.md"
PENDING = "**Pending**: the real-TV session has not run yet."
PHASE5_LINE = "Phase 5 builds its device profile from the rows marked Direct play or Remux above."


def committed_doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def verdict_doc(tg: ModuleType, mc: ModuleType, headline: str, *, results: dict | None = None) -> str:
    """The committed document with a fully tested matrix and a verdict block for the headline."""
    text = committed_doc()
    results = results if results is not None else all_gating_ok(mc)
    text = tg.replace_matrix(text, tg.render_matrix(results, {}))
    head, _, _ = text.partition("## Verdict")
    transcoding = tg.transcoding_line(results)
    common = [transcoding, "Jellyfin version tested: 12.3.0 (image tag 12.3.20261023-013714)"]
    if headline == "GO":
        body = ["**GO**", "", PHASE5_LINE, ""] + common
    elif headline == "NO-GO":
        body = [
            "**NO-GO**",
            "",
            "Mitigation chosen: re-encode. Rows A04 and A16 ended in Video transcode.",
            "",
            *common,
        ]
    else:
        body = [
            "**GO with conditions**",
            "",
            "- No DTS: rows A04, A08 and A12 do not pass.",
            "",
            "Mitigation for the rest: re-encode",
            "",
            *common,
        ]
    return head + "## Verdict\n\n" + "\n".join(body) + "\n"


def test_the_committed_doc_is_valid(tg: ModuleType) -> None:
    assert tg.validate_doc(committed_doc()) == []


def test_the_committed_doc_has_the_ui_spec_skeleton(tg: ModuleType, mc: ModuleType) -> None:
    text = committed_doc()
    headings = [ln for ln in text.splitlines() if ln.startswith("## ")]

    assert text.startswith("# TV compatibility\n")
    assert headings == [
        *("## " + h for _, h, _ in mc.GROUPS),
        "## Address check",
        "## Streaming bitrate",
        "## Verdict",
    ]
    assert "V0003.09.60A.Q0707" in text
    assert PENDING in text.splitlines()
    assert text.count(tg.MATRIX_BEGIN) == 1 and text.count(tg.MATRIX_END) == 1


def test_the_committed_doc_is_the_untested_matrix(tg: ModuleType) -> None:
    text = committed_doc()
    matrix = text[text.index(tg.MATRIX_BEGIN) : text.index(tg.MATRIX_END)]

    assert tg.render_matrix({}, {}) in matrix


def mutate_cell(text: str, row_id: str, column: int, value: str) -> str:
    out = []
    for line in text.splitlines():
        if line.startswith(f"| {row_id} |"):
            cells = line.strip().strip("|").split("|")
            cells[column] = f" {value} "
            line = "|" + "|".join(cells) + "|"
        out.append(line)
    return "\n".join(out) + "\n"


def swap_rows(text: str, first: str, second: str) -> str:
    lines = text.splitlines()
    i = next(n for n, ln in enumerate(lines) if ln.startswith(f"| {first} |"))
    j = next(n for n, ln in enumerate(lines) if ln.startswith(f"| {second} |"))
    lines[i], lines[j] = lines[j], lines[i]
    return "\n".join(lines) + "\n"


def drop_row(text: str, row_id: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not ln.startswith(f"| {row_id} |")) + "\n"


def test_a_blank_cell_is_caught(tg: ModuleType) -> None:
    problems = tg.validate_doc(mutate_cell(committed_doc(), "A05", 7, ""))

    assert any("A05" in p and "empty" in p for p in problems)


def test_an_unknown_method_is_caught(tg: ModuleType) -> None:
    problems = tg.validate_doc(mutate_cell(committed_doc(), "A05", 6, "Transcode"))

    assert any("A05" in p and "Method" in p for p in problems)


def test_an_unknown_answer_is_caught(tg: ModuleType) -> None:
    problems = tg.validate_doc(mutate_cell(committed_doc(), "A05", 8, "maybe"))

    assert any("A05" in p and "Picture and sound OK" in p for p in problems)


def test_two_swapped_rows_are_caught(tg: ModuleType) -> None:
    problems = tg.validate_doc(swap_rows(committed_doc(), "A03", "A04"))

    assert any("order" in p for p in problems)


def test_a_missing_catalogue_row_is_caught(tg: ModuleType) -> None:
    problems = tg.validate_doc(drop_row(committed_doc(), "A10"))

    assert any("A10" in p for p in problems)


def test_a_changed_clip_cell_is_caught(tg: ModuleType) -> None:
    problems = tg.validate_doc(mutate_cell(committed_doc(), "A02", 3, "AAC"))

    assert any("A02" in p and "Audio" in p for p in problems)


def test_a_second_table_in_a_group_is_caught(tg: ModuleType) -> None:
    text = committed_doc().replace("## Subtitles\n", "## Subtitles\n\n" + tg.HEADER + "\n", 1)

    assert tg.validate_doc(text)


def test_an_extra_heading_or_a_missing_one_is_caught(tg: ModuleType) -> None:
    assert tg.validate_doc(committed_doc().replace("## Address check\n", "## Addresses\n"))
    assert tg.validate_doc(committed_doc() + "\n## Notes\n")
    assert tg.validate_doc(committed_doc().replace("# TV compatibility", "# TV notes", 1))


def test_a_matrix_without_its_markers_is_caught(tg: ModuleType) -> None:
    assert tg.validate_doc(committed_doc().replace(tg.MATRIX_END, ""))


def test_an_ip_address_is_caught(tg: ModuleType) -> None:
    problems = tg.validate_doc(committed_doc() + f"\nThe TV was at {LAN_ADDRESS} then.\n")

    assert any("address" in p.lower() for p in problems)


def test_a_mac_address_is_caught(tg: ModuleType) -> None:
    problems = tg.validate_doc(committed_doc() + "\nSeen as aa:bb:cc:dd:ee:ff once.\n")

    assert any("MAC" in p for p in problems)


@pytest.mark.parametrize(
    "line",
    [
        "Serial number: 123",
        "serial = ABC123",
        "| Device ID | 99887766 |",
        "Netflix ESN: NFANDROID1-x",
        "MAC address: unknown-but-a-value",
    ],
)
def test_a_serial_esn_or_device_id_with_a_value_is_caught(tg: ModuleType, line: str) -> None:
    problems = tg.validate_doc(committed_doc() + "\n" + line + "\n")

    assert any("device" in p.lower() or "serial" in p.lower() for p in problems)


def test_the_words_alone_are_allowed(tg: ModuleType) -> None:
    sentence = "No serial number, device ID, Netflix ESN or MAC address is recorded."
    text = committed_doc().replace("\n## Verdict", f"\n{sentence}\n\n## Verdict")

    assert tg.validate_doc(text) == []


def test_a_verdict_must_open_with_a_known_headline(tg: ModuleType) -> None:
    text = committed_doc().replace(PENDING, "**Maybe**")

    assert tg.validate_doc(text)


def test_a_valid_go_doc_passes(tg: ModuleType, mc: ModuleType) -> None:
    assert tg.validate_doc(verdict_doc(tg, mc, "GO")) == []


def test_a_valid_no_go_doc_passes(tg: ModuleType, mc: ModuleType) -> None:
    results = all_gating_ok(mc)
    results["A04"] = [played("Video transcode", "no")]

    assert tg.validate_doc(verdict_doc(tg, mc, "NO-GO", results=results)) == []


def test_a_valid_conditions_doc_passes(tg: ModuleType, mc: ModuleType) -> None:
    assert tg.validate_doc(verdict_doc(tg, mc, "GO with conditions")) == []


def test_go_while_a_gating_row_is_not_tested_is_caught(tg: ModuleType, mc: ModuleType) -> None:
    results = all_gating_ok(mc)
    del results["A07"]

    problems = tg.validate_doc(verdict_doc(tg, mc, "GO", results=results))

    assert any("A07" in p and "not tested" in p for p in problems)


def test_a_go_without_the_phase_5_line_is_caught(tg: ModuleType, mc: ModuleType) -> None:
    assert tg.validate_doc(verdict_doc(tg, mc, "GO").replace(PHASE5_LINE, ""))


def test_a_no_go_without_a_named_mitigation_is_caught(tg: ModuleType, mc: ModuleType) -> None:
    text = verdict_doc(tg, mc, "NO-GO")

    assert tg.validate_doc(text.replace("Mitigation chosen: re-encode.", "Mitigation chosen: none."))
    assert tg.validate_doc(text.replace("Mitigation chosen:", "Plan:"))
    assert tg.validate_doc(text.replace("re-encode", "plan B stick")) == []
    assert tg.validate_doc(text.replace("re-encode", "stronger hardware")) == []


def test_conditions_need_a_bullet_naming_a_row_and_a_mitigation_for_the_rest(tg: ModuleType, mc: ModuleType) -> None:
    text = verdict_doc(tg, mc, "GO with conditions")

    assert tg.validate_doc(text.replace("rows A04, A08 and A12", "all DTS rows"))
    assert tg.validate_doc(text.replace("- No DTS", "No DTS"))
    assert tg.validate_doc(text.replace("Mitigation for the rest:", "Rest:"))


@pytest.mark.parametrize("headline", ["GO", "NO-GO", "GO with conditions"])
def test_a_headline_needs_the_transcoding_line_and_the_version_line(tg: ModuleType, mc: ModuleType, headline: str) -> None:
    text = verdict_doc(tg, mc, headline)
    lines = text.splitlines()

    without_transcoding = "\n".join(ln for ln in lines if not ln.startswith("1080p content needed"))
    without_version = "\n".join(ln for ln in lines if not ln.startswith("Jellyfin version tested: "))

    assert tg.validate_doc(without_transcoding)
    assert tg.validate_doc(without_version)


def test_render_into_the_committed_doc_without_results_reproduces_it_byte_for_byte(
    tg: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    copy = tmp_path / "doc.md"
    copy.write_text(committed_doc(), encoding="utf-8")
    monkeypatch.setattr(tg, "load_manifest", dict)

    args = type("Args", (), {"doc": str(copy), "out": None, "results": str(tmp_path / "none.json")})()
    assert tg.cmd_render(args) == 0

    assert copy.read_text(encoding="utf-8") == committed_doc()


def test_render_into_a_doc_puts_the_played_rows_in_the_matrix(
    tg: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    copy = tmp_path / "doc.md"
    copy.write_text(committed_doc(), encoding="utf-8")
    store = tg.ResultStore(tmp_path / "results.json")
    store.add("A01", {"row": "A01", "method": "Remux", "reasons": ["ContainerNotSupported"], "ok": "yes"})
    store.save()
    monkeypatch.setattr(tg, "load_manifest", dict)

    args = type("Args", (), {"doc": str(copy), "out": None, "results": str(tmp_path / "results.json")})()
    assert tg.cmd_render(args) == 0

    assert "| A01 | MKV | H.264 | AAC | none | 1080p | Remux | ContainerNotSupported | yes |" in copy.read_text()
    assert tg.validate_doc(copy.read_text()) == []


def test_validate_prints_ok_or_the_violations_and_exits_accordingly(
    tg: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = tmp_path / "good.md"
    good.write_text(committed_doc(), encoding="utf-8")
    bad = tmp_path / "bad.md"
    bad.write_text(committed_doc() + "\nSerial number: 123\n", encoding="utf-8")

    assert tg.cmd_validate(type("Args", (), {"doc": str(good)})()) == 0
    assert capsys.readouterr().out.strip() == "OK"
    assert tg.cmd_validate(type("Args", (), {"doc": str(bad)})()) == 1
    assert "serial" in capsys.readouterr().out.lower()
