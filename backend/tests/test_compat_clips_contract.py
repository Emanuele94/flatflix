"""Contract tests for the Compat clip matrix and the admin-only Compat library (COMPAT-01 to 03).

`scripts/make_compat_clips.py` and `scripts/jellyfin_setup.py` are standalone standard-library
scripts, so they are loaded by path. Only their pure parts are exercised here: no request is made,
no ffmpeg runs and nothing under the real jellyfin folder is touched.
"""

import argparse
import importlib.util
import itertools
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
def js() -> ModuleType:
    return load("flatflix_compat_jellyfin_setup", "jellyfin_setup.py")


@pytest.fixture(scope="module")
def mc() -> ModuleType:
    return load("flatflix_compat_make_compat_clips", "make_compat_clips.py")


def row(mc: ModuleType, row_id: str):
    return next(r for r in mc.CATALOGUE if r.id == row_id)


def probe_json(
    *,
    format_name: str = "matroska,webm",
    video: str = "h264",
    pix_fmt: str = "yuv420p",
    audio: str = "aac",
    subtitle: str | None = None,
    width: int = 1920,
) -> dict:
    streams: list[dict] = [
        {"codec_type": "video", "codec_name": video, "pix_fmt": pix_fmt, "width": width},
        {"codec_type": "audio", "codec_name": audio},
    ]
    if subtitle:
        streams.append({"codec_type": "subtitle", "codec_name": subtitle})
    return {"format": {"format_name": format_name}, "streams": streams}


# --- the catalogue --------------------------------------------------------------------


def test_catalogue_ids_are_unique(mc: ModuleType) -> None:
    ids = [r.id for r in mc.CATALOGUE]

    assert len(ids) == len(set(ids))


def test_the_groups_are_the_five_decided_ones(mc: ModuleType) -> None:
    assert [(key, gating) for key, _, gating in mc.GROUPS] == [
        ("av", True),
        ("subs", True),
        ("pgs", False),
        ("uhd", False),
        ("real", False),
    ]
    assert mc.GROUPS[0][1] == "1080p video and audio"


def test_the_av_group_is_a01_to_a24_in_container_video_audio_order(mc: ModuleType) -> None:
    av = [r for r in mc.CATALOGUE if r.group == "av"]

    assert [r.id for r in av] == [f"A{n:02d}" for n in range(1, 25)]
    assert [(r.container, r.video, r.audio) for r in av] == [
        (container, video, audio)
        for container in ("MKV", "MP4")
        for video in ("H.264", "HEVC 8-bit", "HEVC 10-bit")
        for audio in ("AAC", "AC3", "EAC3", "DTS")
    ]
    assert {r.resolution for r in av} == {"1080p"}
    assert {r.subtitles for r in av} == {"none"}


@pytest.mark.parametrize(
    ("group", "ids"),
    [
        ("subs", ["S01", "S02", "S03", "S04"]),
        ("pgs", ["P01"]),
        ("uhd", ["K01", "K02", "K03"]),
        ("real", ["R01", "R02", "R03"]),
    ],
)
def test_the_other_groups_hold_the_decided_rows(mc: ModuleType, group: str, ids: list[str]) -> None:
    assert [r.id for r in mc.CATALOGUE if r.group == group] == ids


def test_only_the_av_and_subs_rows_gate(mc: ModuleType) -> None:
    for r in mc.CATALOGUE:
        assert r.gating is (r.group in ("av", "subs")), r.id


def test_every_row_belongs_to_a_known_group(mc: ModuleType) -> None:
    keys = {key for key, _, _ in mc.GROUPS}

    assert {r.group for r in mc.CATALOGUE} <= keys


def test_the_pgs_row_carries_the_decided_note(mc: ModuleType) -> None:
    assert row(mc, "P01").note == "no PGS encoder in ffmpeg (D-99)"


def test_the_subtitle_rows_use_the_decided_cells(mc: ModuleType) -> None:
    assert [(r.container, r.subtitles) for r in mc.CATALOGUE if r.group == "subs"] == [
        ("MKV", "SRT (external file)"),
        ("MKV", "SRT (embedded)"),
        ("MKV", "ASS (embedded)"),
        ("MP4", "MP4 text (embedded)"),
    ]


def test_the_uhd_rows_are_2160p_downloads(mc: ModuleType) -> None:
    uhd = [r for r in mc.CATALOGUE if r.group == "uhd"]

    assert {r.resolution for r in uhd} == {"2160p"}
    assert {r.origin for r in uhd} == {"download"}
    assert row(mc, "K01").video == "HEVC 10-bit HDR10"


# --- file names -----------------------------------------------------------------------


def test_clip_path_of_a01(mc: ModuleType) -> None:
    assert mc.clip_path(row(mc, "A01")) == mc.SCRATCH / "Compat" / "A01 MKV H264 AAC.mkv"


def test_every_clip_file_name_starts_with_its_id_and_a_space(mc: ModuleType) -> None:
    for r in mc.CATALOGUE:
        assert mc.clip_path(r).name.startswith(f"{r.id} "), r.id


def test_clip_paths_are_unique(mc: ModuleType) -> None:
    names = [mc.clip_path(r).name for r in mc.CATALOGUE]

    assert len(names) == len(set(names))


def test_rows_that_differ_only_in_audio_have_different_files(mc: ModuleType) -> None:
    assert mc.clip_path(row(mc, "A01")) != mc.clip_path(row(mc, "A02"))


# --- mux arguments --------------------------------------------------------------------


def pairs(args: list[str]) -> list[tuple[str, str]]:
    return list(itertools.pairwise(args))


def test_mux_args_of_a01_copies_both_streams_and_tags_the_audio_english(mc: ModuleType) -> None:
    args = mc.mux_args(row(mc, "A01"), Path("v.mkv"), Path("a.mka"), Path("out.part"))

    assert ("-map", "0:v:0") in pairs(args)
    assert ("-map", "1:a:0") in pairs(args)
    assert ("-c", "copy") in pairs(args)
    assert ("-metadata:s:a:0", "language=eng") in pairs(args)
    assert ("-f", "matroska") in pairs(args)
    assert "-tag:v" not in args
    assert args[-1] == "out.part"


def test_mux_args_of_an_mp4_hevc_row_carries_the_hvc1_tag_and_faststart(mc: ModuleType) -> None:
    mp4_hevc = next(
        r for r in mc.CATALOGUE if r.group == "av" and r.container == "MP4" and "HEVC" in r.video
    )

    args = mc.mux_args(mp4_hevc, Path("v.mkv"), Path("a.mka"), Path("out.part"))

    assert ("-tag:v", "hvc1") in pairs(args)
    assert ("-movflags", "+faststart") in pairs(args)
    assert ("-f", "mp4") in pairs(args)


def test_mux_args_of_an_mp4_h264_row_has_faststart_and_no_hevc_tag(mc: ModuleType) -> None:
    mp4_h264 = next(
        r for r in mc.CATALOGUE if r.group == "av" and r.container == "MP4" and r.video == "H.264"
    )

    args = mc.mux_args(mp4_h264, Path("v.mkv"), Path("a.mka"), Path("out.part"))

    assert ("-movflags", "+faststart") in pairs(args)
    assert "-tag:v" not in args


# --- expected streams and the ffprobe comparison --------------------------------------


def test_expected_streams_of_a01(mc: ModuleType) -> None:
    assert mc.expected_streams(row(mc, "A01")) == {
        "container": "matroska",
        "video": "h264",
        "pix_fmt": "yuv420p",
        "audio": "aac",
        "subtitles": None,
    }


def test_expected_streams_of_an_hevc_10_bit_row(mc: ModuleType) -> None:
    ten = next(r for r in mc.CATALOGUE if r.group == "av" and r.video == "HEVC 10-bit")

    want = mc.expected_streams(ten)

    assert want["video"] == "hevc"
    assert want["pix_fmt"] == "yuv420p10le"


def test_probe_mismatches_is_empty_for_a_matching_probe(mc: ModuleType) -> None:
    assert mc.probe_mismatches(row(mc, "A01"), probe_json()) == []


def test_probe_mismatches_names_the_pix_fmt_of_an_8_bit_hevc_10_bit_row(mc: ModuleType) -> None:
    ten = next(r for r in mc.CATALOGUE if r.group == "av" and r.video == "HEVC 10-bit")
    want = mc.expected_streams(ten)
    bad = probe_json(
        format_name="matroska,webm" if want["container"] == "matroska" else "mov,mp4,m4a,3gp,3g2,mj2",
        video="hevc",
        pix_fmt="yuv420p",
        audio=want["audio"],
    )

    mismatches = mc.probe_mismatches(ten, bad)

    assert len(mismatches) == 1
    assert "pix_fmt" in mismatches[0]


def test_probe_mismatches_accepts_the_mp4_family_name_for_mp4(mc: ModuleType) -> None:
    mp4_h264 = next(
        r for r in mc.CATALOGUE if r.group == "av" and r.container == "MP4" and r.video == "H.264"
    )
    want = mc.expected_streams(mp4_h264)

    ok = probe_json(format_name="mov,mp4,m4a,3gp,3g2,mj2", audio=want["audio"])

    assert mc.probe_mismatches(mp4_h264, ok) == []


def test_probe_mismatches_reports_one_message_per_differing_field(mc: ModuleType) -> None:
    bad = probe_json(format_name="avi", video="mpeg4", audio="mp3")

    fields = [m.split(":")[0] for m in mc.probe_mismatches(row(mc, "A01"), bad)]

    assert fields == ["container", "video", "audio"]


def test_probe_mismatches_flags_a_missing_audio_stream(mc: ModuleType) -> None:
    silent = {
        "format": {"format_name": "matroska,webm"},
        "streams": [{"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p"}],
    }

    assert [m.split(":")[0] for m in mc.probe_mismatches(row(mc, "A01"), silent)] == ["audio"]


# --- the Compat library ---------------------------------------------------------------


def test_missing_compat_rows_survives_a_cleaned_item_name(js: ModuleType) -> None:
    assert js.missing_compat_rows(["A01 MKV H264 AAC.mkv"], ["A01 MKV"]) == []


def test_missing_compat_rows_names_the_row_id_that_is_not_listed(js: ModuleType) -> None:
    assert js.missing_compat_rows(["A01 MKV H264 AAC.mkv"], []) == ["A01"]


def test_missing_compat_rows_keeps_file_order_and_matches_on_the_first_token_only(
    js: ModuleType,
) -> None:
    files = ["A02 MKV H264 AC3.mkv", "S01 MKV H264 AAC SRTEXT.mkv", "A01 MKV H264 AAC.mkv"]

    assert js.missing_compat_rows(files, ["A01 anything", "S01"]) == ["A02"]
    assert js.missing_compat_rows(files, ["A010 MKV"]) == ["A02", "S01", "A01"]


def test_compat_is_a_homevideos_library_over_scratch_compat(js: ModuleType) -> None:
    assert js.COMPAT_LIBRARY == "Compat"
    assert js.COMPAT_PATH == "/scratch/Compat"
    assert js.COMPAT_TYPE == "homevideos"
    assert js.COMPAT_LIBRARY not in [name for name, _, _ in js.LIBRARIES]


def test_the_compat_library_has_internet_metadata_off(js: ModuleType) -> None:
    assert js.library_options(False)["EnableInternetProviders"] is False
    assert js.library_options(True)["EnableInternetProviders"] is True


def test_the_check_steps_stay_the_same_eleven(js: ModuleType) -> None:
    assert len(js.CHECK_STEPS) == 11
    assert "libraries" in js.CHECK_STEPS


def test_setup_gives_the_household_only_movies_and_tv_series(
    js: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    ensured: list[tuple[str, str, str, bool]] = []
    household_folders: list[list[str]] = []

    class FakeApi:
        pass

    monkeypatch.setattr(js, "passwords", lambda: ("a" * 40, "kt7m3xq9ab"))
    monkeypatch.setattr(js, "configured_bps", lambda: 20_000_000)
    monkeypatch.setattr(js, "wizard_completed", lambda api: True)
    monkeypatch.setattr(js, "Api", lambda base, token=None: FakeApi())
    monkeypatch.setattr(js, "admin_api", lambda base: (FakeApi(), "admin-id"))
    monkeypatch.setattr(js, "apply_server_config", lambda api, bps: False)
    monkeypatch.setattr(js, "ensure_user", lambda api, name, password: ("household-id", "unchanged"))
    monkeypatch.setattr(js, "find_library", lambda api, name: {"ItemId": "x"})

    def fake_ensure(api, name, kind, path, *, internet):
        ensured.append((name, kind, path, internet))
        return f"id-{name}"

    def fake_changes(folder_ids, bps):
        household_folders.append(list(folder_ids))
        return {}

    monkeypatch.setattr(js, "ensure_library", fake_ensure)
    monkeypatch.setattr(js, "household_changes", fake_changes)
    monkeypatch.setattr(js, "apply_policy", lambda api, user_id, changes: False)
    monkeypatch.setattr(js, "apply_prefs", lambda api, user_id: False)

    code = js.cmd_setup(argparse.Namespace(base="http://x", no_scan=True))

    assert code == 0
    assert household_folders == [["id-Movies", "id-TV Series"]]
    assert ("Compat", "homevideos", "/scratch/Compat", False) in ensured
    assert [name for name, *_ in ensured] == ["Movies", "TV Series", "Compat"]


def test_the_libraries_check_reports_a_compat_gap(js: ModuleType) -> None:
    folders = [
        {
            "Name": name,
            "CollectionType": kind,
            "Locations": [path],
            "LibraryOptions": {"SaveLocalMetadata": False, "EnableRealtimeMonitor": True},
        }
        for name, kind, path in js.LIBRARIES
    ]

    assert js.library_gaps(folders) == []
    assert js.compat_gaps(folders) == ["Compat library is missing"]

    folders.append(
        {
            "Name": "Compat",
            "CollectionType": "homevideos",
            "Locations": ["/scratch/Compat"],
            "LibraryOptions": {"EnableInternetProviders": True},
        }
    )

    assert js.compat_gaps(folders) == ["Compat has internet metadata on"]

    folders[-1]["LibraryOptions"]["EnableInternetProviders"] = False

    assert js.compat_gaps(folders) == []


# --- Task 2: the whole matrix ---------------------------------------------------------


def test_mux_args_of_an_mp4_dts_row_carries_strict_minus_two(mc: ModuleType) -> None:
    mp4_dts = next(
        r for r in mc.CATALOGUE if r.group == "av" and r.container == "MP4" and r.audio == "DTS"
    )

    args = mc.mux_args(mp4_dts, Path("v.mkv"), Path("a.mka"), Path("out.part"))

    assert ("-strict", "-2") in pairs(args)


def test_mux_args_of_an_mkv_dts_row_needs_no_strict_flag(mc: ModuleType) -> None:
    mkv_dts = next(
        r for r in mc.CATALOGUE if r.group == "av" and r.container == "MKV" and r.audio == "DTS"
    )

    assert "-strict" not in mc.mux_args(mkv_dts, Path("v.mkv"), Path("a.mka"), Path("out.part"))


@pytest.mark.parametrize(
    ("row_id", "codec"), [("S02", "srt"), ("S03", "ass"), ("S04", "mov_text")]
)
def test_mux_args_of_an_embedded_subtitle_row_maps_the_subtitle_input(
    mc: ModuleType, row_id: str, codec: str
) -> None:
    args = mc.mux_args(
        row(mc, row_id), Path("v.mkv"), Path("a.mka"), Path("out.part"), subtitle=Path("subs.x")
    )

    assert ("-i", "subs.x") in pairs(args)
    assert ("-map", "2:0") in pairs(args)
    assert ("-c:s", codec) in pairs(args)
    assert ("-metadata:s:s:0", "language=eng") in pairs(args)
    assert args[-1] == "out.part"


def test_an_embedded_subtitle_row_without_a_subtitle_file_is_refused(mc: ModuleType) -> None:
    with pytest.raises(ValueError, match="S02"):
        mc.mux_args(row(mc, "S02"), Path("v.mkv"), Path("a.mka"), Path("out.part"))


def test_mux_args_of_the_external_srt_row_has_no_subtitle_stream(mc: ModuleType) -> None:
    args = mc.mux_args(row(mc, "S01"), Path("v.mkv"), Path("a.mka"), Path("out.part"))

    assert "2:0" not in args
    assert "-c:s" not in args


def test_na_reason_is_the_first_non_empty_stderr_line(mc: ModuleType) -> None:
    assert mc.na_reason("\n  \n  Could not write header\nsecond line\n") == (
        "n/a — Could not write header"
    )


def test_na_reason_cuts_a_long_line_to_120_characters(mc: ModuleType) -> None:
    assert mc.na_reason("x" * 300) == "n/a — " + "x" * 120


def test_na_reason_never_returns_an_empty_reason(mc: ModuleType) -> None:
    assert mc.na_reason("").startswith("n/a — ")
    assert len(mc.na_reason("")) > len("n/a — ")


def test_every_test_video_is_pinned_from_the_jellyfin_repository(mc: ModuleType) -> None:
    from urllib.parse import urlparse

    assert sorted(mc.TEST_VIDEOS) == ["K01", "K02", "K03", "R03"]
    for row_id, video in mc.TEST_VIDEOS.items():
        parsed = urlparse(video.url)
        assert parsed.scheme == "https", row_id
        assert parsed.hostname == "repo.jellyfin.org", row_id
        assert len(video.sha256 or "") == 64 and set(video.sha256 or "") <= set("0123456789abcdef")
        assert row_id in mc.ROW_IDS


def test_the_test_videos_match_the_resolution_of_their_rows(mc: ModuleType) -> None:
    for row_id, video in mc.TEST_VIDEOS.items():
        wanted = "4K" if row(mc, row_id).resolution == "2160p" else "1080p"
        assert wanted in video.file, row_id


def test_sidecar_path_of_the_external_srt_row(mc: ModuleType) -> None:
    assert mc.sidecar_path(row(mc, "S01")) == mc.clip_path(row(mc, "S01")).with_suffix(".en.srt")


def test_the_subtitle_texts_carry_twelve_english_cues_each(mc: ModuleType) -> None:
    srt, ass = mc.srt_text(), mc.ass_text()

    assert srt.count(" --> ") == 12
    assert ass.count("Dialogue:") == 12
    assert ass.count("Style:") == 1
    assert "Subtitle test line 12 of 12" in srt
    assert "Subtitle test line 12 of 12" in ass


def test_the_pgs_row_has_no_file_and_the_decided_note(mc: ModuleType) -> None:
    assert mc.build_row(row(mc, "P01")) == {
        "file": None,
        "na": None,
        "note": "no PGS encoder in ffmpeg (D-99)",
        "probed": None,
    }


def test_a_row_the_muxer_refuses_is_recorded_as_na_never_skipped(
    mc: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import subprocess

    monkeypatch.setattr(mc, "SCRATCH", tmp_path)
    monkeypatch.setattr(mc, "video_intermediate", lambda video: tmp_path / "v.mkv")
    monkeypatch.setattr(mc, "audio_intermediate", lambda audio: tmp_path / "a.mka")
    target = next(
        r for r in mc.CATALOGUE if r.group == "av" and r.container == "MP4" and r.audio == "DTS"
    )

    def refuse(*args: str, **kwargs: object) -> None:
        part = Path(args[-1])
        part.write_bytes(b"half")
        raise subprocess.CalledProcessError(1, ["ffmpeg"], stderr="\nmuxer says no\nmore\n")

    monkeypatch.setattr(mc, "ffmpeg", refuse)

    entry = mc.build_row(target)

    assert entry == {"file": None, "na": "n/a — muxer says no", "note": None, "probed": None}
    assert list((tmp_path / "Compat").iterdir()) == []  # no half file is left for a scan to find


def test_the_manifest_merges_rows_in_catalogue_order(
    mc: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(mc, "MANIFEST", tmp_path / "tv-gate" / "clips.json")
    mc.update_manifest({"A02": {"file": "b"}})
    mc.update_manifest({"A01": {"file": "a"}})
    merged = mc.update_manifest({"A02": {"file": "b2"}})

    assert list(merged) == ["A01", "A02"]
    assert merged["A01"] == {"file": "a"}
    assert mc.read_manifest() == merged


def test_a_failed_manifest_write_leaves_the_previous_file_intact(
    mc: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest = tmp_path / "tv-gate" / "clips.json"
    monkeypatch.setattr(mc, "MANIFEST", manifest)
    mc.write_manifest({"A01": {"file": "old"}})
    before = manifest.read_text(encoding="utf-8")

    def break_midway(data: object, handle: object, **kwargs: object) -> None:
        handle.write("{ half")  # type: ignore[attr-defined]
        raise OSError("disk full")

    monkeypatch.setattr(mc.json, "dump", break_midway)

    with pytest.raises(OSError, match="disk full"):
        mc.write_manifest({"A01": {"file": "new"}})

    monkeypatch.undo()
    assert manifest.read_text(encoding="utf-8") == before
    assert [p.name for p in manifest.parent.iterdir()] == ["clips.json"]


def test_the_catalogue_names_are_free_of_copyrighted_sources(mc: ModuleType) -> None:
    from urllib.parse import urlparse

    hosts = {urlparse(s.url).hostname for s in mc.SOURCES.values()}
    hosts |= {urlparse(v.url).hostname for v in mc.TEST_VIDEOS.values()}

    assert hosts == {"download.blender.org", "repo.jellyfin.org"}


def test_nothing_the_script_writes_is_inside_the_repository_tree(mc: ModuleType) -> None:
    import subprocess

    root = Path(__file__).resolve().parents[2]
    for path in (mc.SCRATCH / "Compat" / "x", mc.MANIFEST, mc.INTERMEDIATE_DIR / "x"):
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", str(path)], cwd=root, check=False
        ).returncode
        assert ignored == 0, path
