"""Tests for the pure per-file allowlist (FILT-02, D-14)."""

from app.download.allowlist import (
    EXCLUDED_FILE_PATTERNS,
    OTHER_VIDEO_EXTENSIONS,
    SAMPLE_SIZE_RATIO,
    SUBTITLE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    FileDecision,
    TorrentFile,
    decide,
    final_extension,
    is_sample_name,
)

# Verbatim qBittorrent 5.2.4 `torrents/files` rows (research, Code Examples).
SINTEL_VIDEO_ROW = {"index": 5, "priority": 1, "size": 129241752, "name": "Sintel/Sintel.mp4"}
SINTEL_POSTER_ROW = {"index": 10, "priority": 0, "size": 46115, "name": "Sintel/poster.jpg"}
SINTEL_SUBTITLE_ROW = {"index": 6, "priority": 1, "size": 30000, "name": "Sintel/Sintel.en.srt"}


def test_real_torrent_file_list_is_split_into_keep_and_zero_indexes():
    files = [
        TorrentFile.from_qbit(SINTEL_VIDEO_ROW),
        TorrentFile.from_qbit(SINTEL_POSTER_ROW),
        TorrentFile.from_qbit(SINTEL_SUBTITLE_ROW),
    ]

    decision = decide(files)

    assert decision == FileDecision(accept=True, keep_ids=(5, 6), zero_ids=(10,), reason=None)


def test_from_qbit_maps_index_name_size_priority():
    file = TorrentFile.from_qbit(SINTEL_VIDEO_ROW)

    assert file == TorrentFile(index=5, name="Sintel/Sintel.mp4", size=129241752, priority=1)


# --- Task 2: edge cases -------------------------------------------------------------------

GB = 1024**3
MB = 1024**2


def _files(*specs):
    """Build TorrentFile rows from (name, size) pairs; index is the position."""
    return [
        TorrentFile(index=i, name=name, size=size, priority=1)
        for i, (name, size) in enumerate(specs)
    ]


def test_samples_are_zeroed_and_sampler_is_kept():
    files = _files(
        ("Movie.2020.mkv", 4 * GB),
        ("Movie.Sample.mkv", 50 * MB),
        ("sample/clip.mkv", 4 * GB),
        ("Sampler.mkv", 4 * GB),
    )

    decision = decide(files)

    assert decision.accept is True
    assert decision.keep_ids == (0, 3)
    assert decision.zero_ids == (1, 2)


def test_is_sample_name_matches_only_whole_word():
    assert is_sample_name("Movie.Sample.mkv")
    assert is_sample_name("sample/clip.mkv")
    assert is_sample_name("Movie_SAMPLE-720p.mkv")
    assert not is_sample_name("Sampler.mkv")
    assert not is_sample_name("Resampled/Movie.mkv")


def test_size_boundary_is_exactly_ten_percent_of_largest_video():
    files = _files(("big.mkv", 1000), ("exactly-ten-percent.mkv", 100), ("one-byte-short.mkv", 99))

    decision = decide(files)

    assert decision.keep_ids == (0, 1)
    assert decision.zero_ids == (2,)


def test_full_season_is_kept_and_small_featurette_is_zeroed():
    episodes = [(f"Show S01/Show.S01E{n:02d}.mkv", 1 * GB) for n in range(1, 11)]
    files = _files(*episodes, ("Show S01/Extras/Featurette.mkv", 50 * MB))

    decision = decide(files)

    assert decision.accept is True
    assert decision.keep_ids == tuple(range(10))
    assert decision.zero_ids == (10,)


def test_double_extension_uses_final_suffix_only():
    files = _files(("a/main.mkv", GB), ("movie.mkv.exe", GB), ("movie.exe.mkv", GB))

    decision = decide(files)

    assert decision.keep_ids == (0, 2)
    assert decision.zero_ids == (1,)
    assert final_extension("movie.mkv.exe") == ".exe"
    assert final_extension("movie.exe.mkv") == ".mkv"


def test_extension_check_is_case_insensitive():
    files = _files(("MOVIE.MKV", GB), ("SETUP.EXE", GB))

    decision = decide(files)

    assert decision.keep_ids == (0,)
    assert decision.zero_ids == (1,)


def test_file_without_extension_is_zeroed():
    files = _files(("Film/Film.mkv", GB), ("Film/README", 1000))

    decision = decide(files)

    assert decision.keep_ids == (0,)
    assert decision.zero_ids == (1,)
    assert final_extension("README") == ""


def test_non_ascii_and_nested_paths_are_kept():
    files = _files(("Città/Film.mkv", GB), ("Città/Sub/Film.it.srt", 20000))

    decision = decide(files)

    assert decision.accept is True
    assert decision.keep_ids == (0, 1)
    assert decision.zero_ids == ()


def test_empty_torrent_is_rejected_as_no_video():
    assert decide([]) == FileDecision(accept=False, keep_ids=(), zero_ids=(), reason="no_video")


def test_subtitles_only_torrent_is_rejected_with_every_index_zeroed():
    decision = decide(_files(("a.srt", 1000), ("b.ass", 2000)))

    assert decision == FileDecision(accept=False, keep_ids=(), zero_ids=(0, 1), reason="no_video")


def test_non_allowed_only_torrent_is_rejected_with_every_index_zeroed():
    decision = decide(_files(("a.txt", 1000), ("b.nfo", 2000)))

    assert decision == FileDecision(accept=False, keep_ids=(), zero_ids=(0, 1), reason="no_video")


def test_samples_only_torrent_is_rejected_with_every_index_zeroed():
    decision = decide(_files(("Movie.Sample.mkv", 50 * MB), ("sample/clip.mp4", 40 * MB)))

    assert decision == FileDecision(accept=False, keep_ids=(), zero_ids=(0, 1), reason="no_video")


def test_a_webm_film_is_rejected_as_video_format_with_every_index_zeroed():
    decision = decide(_files(("Movie.webm", 1200 * MB), ("Movie.en.srt", 40_000)))

    assert decision == FileDecision(
        accept=False, keep_ids=(), zero_ids=(0, 1), reason="video_format"
    )


def test_an_upper_case_webm_extension_is_rejected_as_video_format():
    assert decide(_files(("Movie.WEBM", GB))).reason == "video_format"


def test_a_webm_film_with_only_a_sample_beside_it_is_rejected_as_video_format():
    decision = decide(_files(("Movie.webm", 2 * GB), ("Sample/sample.mkv", 30 * MB)))

    assert decision.accept is False
    assert decision.reason == "video_format"


def test_a_webm_sample_alone_is_rejected_as_no_video():
    assert decide(_files(("Movie.sample.webm", 30 * MB))).reason == "no_video"


def test_a_mixed_mkv_and_webm_torrent_keeps_only_the_mkv():
    decision = decide(_files(("Movie.mkv", 2 * GB), ("Movie.webm", 2 * GB)))

    assert decision == FileDecision(accept=True, keep_ids=(0,), zero_ids=(1,), reason=None)


def test_the_filt02_video_list_is_unchanged_and_webm_is_never_in_it():
    assert VIDEO_EXTENSIONS == {".mkv", ".mp4", ".avi", ".m4v"}
    assert ".webm" not in VIDEO_EXTENSIONS


def test_the_other_video_formats_only_name_a_rejection_and_overlap_no_allowed_list():
    assert ".webm" in OTHER_VIDEO_EXTENSIONS
    assert OTHER_VIDEO_EXTENSIONS.isdisjoint(VIDEO_EXTENSIONS)
    assert OTHER_VIDEO_EXTENSIONS.isdisjoint(SUBTITLE_EXTENSIONS)


def test_a_big_other_format_film_with_a_small_allowed_trailer_is_rejected_as_video_format():
    decision = decide(_files(("Movie/Movie.m2ts", 20 * GB), ("Movie/Trailer.mp4", 100 * MB)))

    assert decision == FileDecision(
        accept=False, keep_ids=(), zero_ids=(0, 1), reason="video_format"
    )


def test_a_big_other_format_film_beside_an_mkv_of_a_fifth_keeps_the_mkv_and_the_subtitle():
    decision = decide(
        _files(("Movie.m2ts", 20 * GB), ("Movie.mkv", 4 * GB), ("Movie.srt", 2048))
    )

    assert decision == FileDecision(accept=True, keep_ids=(1, 2), zero_ids=(0,), reason=None)


def test_the_ten_percent_boundary_is_measured_against_a_video_of_any_format():
    exact = decide(_files(("Movie.webm", 10 * GB), ("Movie.mkv", 1 * GB)))
    short = decide(_files(("Movie.webm", 10 * GB), ("Movie.mkv", 1 * GB - 1)))

    assert exact == FileDecision(accept=True, keep_ids=(1,), zero_ids=(0,), reason=None)
    assert short.accept is False
    assert short.reason == "video_format"
    assert short.keep_ids == ()


def test_a_sample_named_video_of_another_format_never_sizes_the_main_video():
    decision = decide(_files(("Sample/sample.m2ts", 20 * GB), ("Movie.mp4", 700 * MB)))

    assert decision == FileDecision(accept=True, keep_ids=(1,), zero_ids=(0,), reason=None)


def test_single_main_video_is_accepted_with_nothing_zeroed():
    decision = decide(_files(("Movie.mkv", 2 * GB)))

    assert decision == FileDecision(accept=True, keep_ids=(0,), zero_ids=(), reason=None)


def test_excluded_file_patterns_start_with_the_filt01_list_in_order():
    assert EXCLUDED_FILE_PATTERNS[:11] == (
        "*.exe", "*.bat", "*.cmd", "*.ps1", "*.scr", "*.lnk",
        "*.msi", "*.zip", "*.rar", "*.7z", "*.iso",
    )  # fmt: skip


def test_excluded_file_patterns_are_lower_case_and_unique():
    assert all(p == p.lower() for p in EXCLUDED_FILE_PATTERNS)
    assert len(set(EXCLUDED_FILE_PATTERNS)) == len(EXCLUDED_FILE_PATTERNS)
    assert SAMPLE_SIZE_RATIO == 0.10
