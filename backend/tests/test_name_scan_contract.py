"""Contract tests for the naming scan test (NAME-01, D-90 to D-93, D-101).

`scripts/name_scan.py` is a standalone standard-library script, so it is loaded by path. Only its
pure parts and a throw-away build in a temporary scratch folder are exercised here: no request is
made and nothing under the real jellyfin folder is touched. Real captured torrent names never
appear in this file (D-101); the names below are synthetic or made up on the spot.
"""

import importlib.util
import json
import shutil
import sys
import unicodedata
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


def load(name: str, filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses looks its own module up here
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ns() -> ModuleType:
    return load("flatflix_name_scan", "name_scan.py")


def film(title: str, year: int, name: str = "x", **extra: object) -> dict:
    return {
        "name": name,
        "kind": "film",
        "truth": {"title": title, "year": year},
        "confirmed": True,
        **extra,
    }


def episode(series: str, season: int, number: int, name: str = "x", **extra: object) -> dict:
    return {
        "name": name,
        "kind": "episode",
        "truth": {"series": series, "season": season, "episode": number},
        "confirmed": True,
        **extra,
    }


# --- normalise -----------------------------------------------------------------------


def test_normalise_folds_punctuation_and_case(ns: ModuleType) -> None:
    assert ns.normalise("Agent 327: Operation Barbershop") == ns.normalise(
        "Agent.327 Operation-Barbershop"
    )
    assert ns.normalise("  AGENT   327 ") == "agent 327"


def test_normalise_treats_decomposed_and_composed_accents_alike(ns: ModuleType) -> None:
    composed = "Amélie"
    decomposed = unicodedata.normalize("NFD", composed)
    assert composed != decomposed
    assert ns.normalise(composed) == ns.normalise(decomposed)


def test_normalise_of_only_punctuation_is_empty(ns: ModuleType) -> None:
    assert ns.normalise("...---") == ""


# --- safe_component ------------------------------------------------------------------


def test_safe_component_replaces_separators_and_control_characters(ns: ModuleType) -> None:
    assert ns.safe_component("a/b\x00c") == "a_b_c"
    assert ns.safe_component("tab\there\nline") == "tab_here_line"
    assert ns.safe_component("back\\slash") == "back_slash"


def test_safe_component_strips_leading_dots_so_no_traversal(ns: ModuleType) -> None:
    assert not ns.safe_component(".hidden").startswith(".")
    assert ns.safe_component("..") not in {"", ".", ".."}
    assert ns.safe_component("") not in {"", ".", ".."}


def test_safe_component_cuts_to_the_byte_cap_without_splitting_a_character(ns: ModuleType) -> None:
    name = "é" * 150  # 300 bytes in UTF-8
    cut = ns.safe_component(name)
    assert len(cut.encode("utf-8")) <= ns.MAX_COMPONENT_BYTES
    assert set(cut) == {"é"}  # every kept character is whole
    assert len(ns.safe_component("a" * 300).encode("utf-8")) == ns.MAX_COMPONENT_BYTES


# --- layout --------------------------------------------------------------------------


def test_layout_of_a_single_file_torrent_is_the_library_root(ns: ModuleType) -> None:
    name = "Sintel.2010.720p.WEB-DL.AAC.H264.mkv"
    assert ns.layout({"name": name, "kind": "film"}) == Path("Movies") / name


def test_layout_of_a_folder_torrent_keeps_the_folder_with_the_file_inside(ns: ModuleType) -> None:
    name = "Big.Buck.Bunny.2008.1080p.BluRay.x264-OPEN"
    assert ns.layout({"name": name, "kind": "film"}) == Path("Movies") / name / (name + ".mkv")


def test_layout_uses_the_inner_file_name_when_given(ns: ModuleType) -> None:
    entry = {"name": "Show.S01.COMPLETE", "kind": "episode", "inner": "Show.S01E01.mkv"}
    assert ns.layout(entry) == Path("TV") / "Show.S01.COMPLETE" / "Show.S01E01.mkv"


def test_layout_keeps_the_video_extension_of_a_name_over_the_byte_cap(ns: ModuleType) -> None:
    for ext in (".mkv", ".MP4"):
        name = "A" * 230 + ext  # a scene-style name between 201 and 255 bytes
        file_name = ns.layout({"name": name, "kind": "film"}).name
        assert file_name.endswith(ext)
        assert len(file_name.encode("utf-8")) <= ns.MAX_COMPONENT_BYTES


def test_layout_keeps_the_extension_of_a_long_inner_file_name(ns: ModuleType) -> None:
    entry = {"name": "Show.S01.COMPLETE", "kind": "episode", "inner": "é" * 120 + ".mkv"}
    file_name = ns.layout(entry).name
    assert file_name.endswith(".mkv")
    assert len(file_name.encode("utf-8")) <= ns.MAX_COMPONENT_BYTES
    assert set(file_name[:-4]) == {"é"}  # cut on a character boundary


def test_layout_of_a_bare_extension_name_still_yields_a_named_file(ns: ModuleType) -> None:
    assert ns.layout({"name": ".mkv", "kind": "film"}) == Path("Movies") / "unnamed.mkv"


def test_layout_puts_episodes_under_tv(ns: ModuleType) -> None:
    assert ns.layout({"name": "Show.S01E02.mkv", "kind": "episode"}).parts[0] == "TV"


def test_layout_never_escapes_the_raw_folder(ns: ModuleType) -> None:
    path = ns.layout({"name": "../../etc/passwd", "kind": "film"})
    assert ".." not in path.parts
    assert path.parts[0] == "Movies"


# --- classify: films -----------------------------------------------------------------


def jf(name: str, year: int | None, ids: dict | None = None) -> dict:
    return {"Name": name, "ProductionYear": year, "ProviderIds": {"Tmdb": "1"} if ids is None else ids}


def test_classify_film_with_equal_title_and_year_is_identified(ns: ModuleType) -> None:
    assert ns.classify(film("Sintel", 2010), jf("Sintel", 2010)) == "identified"
    assert ns.classify(film("Agent 327: Operation Barbershop", 2017),
                       jf("Agent 327 - Operation Barbershop", 2017)) == "identified"


def test_classify_film_without_a_provider_id_is_unidentified(ns: ModuleType) -> None:
    assert ns.classify(film("Sintel", 2010), jf("Sintel", 2010, {})) == "unidentified"
    assert ns.classify(film("Sintel", 2010), None) == "unidentified"


def test_classify_film_with_another_title_or_year_is_wrong_title(ns: ModuleType) -> None:
    # a provider id for the 1982 film while the truth is the 2017 one
    assert ns.classify(film("Another Film", 2017), jf("Another Film", 1982)) == "wrong title"
    assert ns.classify(film("Another Film", 2017), jf("Other Name", 2017)) == "wrong title"
    assert ns.classify(film("Another Film", 2017), jf("Another Film", None)) == "wrong title"


def test_an_imdb_id_alone_counts_as_identification(ns: ModuleType) -> None:
    assert ns.classify(film("Sintel", 2010), jf("Sintel", 2010, {"Imdb": "tt1"})) == "identified"


# --- classify: episodes --------------------------------------------------------------


def ep(series_id: str | None, season: int | None, number: int | None) -> dict:
    return {
        "SeriesId": series_id,
        "SeriesName": "ignored",
        "ParentIndexNumber": season,
        "IndexNumber": number,
        "ProviderIds": {},
    }


def series(name: str, ids: dict | None = None) -> dict:
    return {"Id": "s1", "Name": name, "ProviderIds": {"Tmdb": "9"} if ids is None else ids}


def test_classify_episode_without_a_series_link_is_unidentified(ns: ModuleType) -> None:
    truth = episode("Pioneer One", 1, 2)
    assert ns.classify(truth, ep(None, None, 2), None) == "unidentified"
    assert ns.classify(truth, None, None) == "unidentified"


def test_classify_episode_of_another_series_is_wrong_title(ns: ModuleType) -> None:
    assert (
        ns.classify(episode("Pioneer One", 1, 2), ep("s1", 1, 2), series("Another Show"))
        == "wrong title"
    )


def test_classify_episode_with_no_season_or_number_is_unidentified(ns: ModuleType) -> None:
    truth = episode("Pioneer One", 1, 2)
    assert ns.classify(truth, ep("s1", None, 2), series("Pioneer One")) == "unidentified"
    assert ns.classify(truth, ep("s1", 1, None), series("Pioneer One")) == "unidentified"


def test_classify_episode_with_other_numbers_is_wrong_title(ns: ModuleType) -> None:
    truth = episode("Pioneer One", 1, 2)
    assert ns.classify(truth, ep("s1", 1, 3), series("Pioneer One")) == "wrong title"
    assert ns.classify(truth, ep("s1", 2, 2), series("Pioneer One")) == "wrong title"


def test_classify_episode_with_everything_equal_is_identified(ns: ModuleType) -> None:
    truth = episode("Pioneer One", 1, 2)
    assert ns.classify(truth, ep("s1", 1, 2), series("pioneer-one")) == "identified"


def test_numbers_compare_as_integers(ns: ModuleType) -> None:
    truth = episode("Pioneer One", 1, 2)
    assert ns.classify(truth, ep("s1", "01", "2"), series("Pioneer One")) == "identified"
    assert ns.classify(film("Sintel", 2010), jf("Sintel", "2010")) == "identified"


# --- verdict -------------------------------------------------------------------------


def rows(identified: int, unidentified: int = 0, wrong: int = 0) -> list[dict]:
    out = [{"result": "identified"}] * identified
    out += [{"result": "unidentified"}] * unidentified
    out += [{"result": "wrong title"}] * wrong
    return out


def test_verdict_meets_the_bar_at_exactly_ninety_percent(ns: ModuleType) -> None:
    result = ns.verdict(rows(27, 3))
    assert result["meets_bar"] is True
    assert (result["total"], result["identified"], result["unidentified"], result["wrong"]) == (
        30, 27, 3, 0)
    assert result["percent"] == 90


def test_verdict_misses_the_bar_below_ninety_percent(ns: ModuleType) -> None:
    assert ns.verdict(rows(26, 4))["meets_bar"] is False


def test_verdict_with_one_wrong_title_never_meets_the_bar(ns: ModuleType) -> None:
    assert ns.verdict(rows(29, 0, 1))["meets_bar"] is False


def test_verdict_of_no_names_does_not_meet_the_bar(ns: ModuleType) -> None:
    result = ns.verdict([])
    assert result["meets_bar"] is False
    assert result["total"] == 0 and result["percent"] == 0


def test_verdict_percent_never_rounds_up_to_the_bar(ns: ModuleType) -> None:
    result = ns.verdict(rows(269, 31))  # 89.67 %
    assert result["percent"] == 89 and result["meets_bar"] is False


# --- render_table --------------------------------------------------------------------


def test_render_table_has_one_row_per_name_and_the_four_columns(ns: ModuleType) -> None:
    table = ns.render_table(
        [
            {"name": "A|B", "expected": "A (2000)", "matched": "A (2000)", "result": "identified"},
            {"name": "C", "expected": "C (2001)", "matched": "-", "result": "unidentified"},
        ]
    )
    lines = table.strip().splitlines()
    assert lines[0] == "| Name | Expected | Jellyfin matched | Result |"
    assert len(lines) == 2 + 2
    assert "A\\|B" in lines[2]


# --- validate_corpus -----------------------------------------------------------------


def test_validate_corpus_reports_an_empty_corpus(ns: ModuleType) -> None:
    assert ns.validate_corpus([]) == ["corpus is empty"]


def test_validate_corpus_reports_each_problem_with_its_index(ns: ModuleType) -> None:
    entries = [
        film("Sintel", 2010, "Sintel.2010.mkv"),
        {**film("Sintel", 2010, "Sintel.2010.mkv")},
        {**film("Spring", 2019, "Spring.2019.mkv"), "confirmed": False},
        {"name": "Missing.truth", "kind": "film", "truth": {"title": "X"}, "confirmed": True},
        {"name": "Null.truth", "kind": "episode", "truth": None, "confirmed": True},
    ]
    problems = ns.validate_corpus(entries)
    text = "\n".join(problems)
    assert "entry 1" in text and "duplicate" in text
    assert "entry 2" in text and "confirm" in text
    assert "entry 3" in text and "truth" in text
    assert "entry 4" in text
    assert not any(p.startswith("entry 0") for p in problems)
    # real names are never echoed back
    assert "Sintel.2010.mkv" not in text and "Missing.truth" not in text


def test_validate_corpus_reports_two_names_that_share_one_path(ns: ModuleType) -> None:
    entries = [
        film("A", 2000, "Same/Name"),
        film("A", 2000, "Same_Name"),
    ]
    assert any("same path" in p for p in ns.validate_corpus(entries))


def test_the_committed_sample_validates_clean(ns: ModuleType) -> None:
    entries = json.loads((ns.SAMPLE).read_text(encoding="utf-8"))
    assert ns.validate_corpus(entries) == []
    assert 8 <= len(entries) <= 12
    assert any(e["name"].startswith("Pioneer.One") for e in entries)


# --- build_raw -----------------------------------------------------------------------


def test_build_raw_refuses_a_raw_folder_outside_the_scratch_folder(
    ns: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ns, "SCRATCH", tmp_path / "scratch")
    monkeypatch.setattr(ns, "RAW", tmp_path / "elsewhere" / "Raw")
    with pytest.raises(ns.Fail) as caught:
        ns.build_raw([film("Sintel", 2010, "Sintel.2010.mkv")])
    assert caught.value.step == "corpus"
    assert not (tmp_path / "elsewhere").exists()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="host ffmpeg missing")
def test_build_raw_rebuilds_only_movies_and_tv(
    ns: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scratch = tmp_path / "scratch"
    keep = scratch / "Compat" / "keep.txt"
    keep.parent.mkdir(parents=True)
    keep.write_text("untouched")
    stale = scratch / "Raw" / "Movies" / "stale.mkv"
    stale.parent.mkdir(parents=True)
    stale.write_text("old")
    monkeypatch.setattr(ns, "SCRATCH", scratch)
    monkeypatch.setattr(ns, "RAW", scratch / "Raw")
    entries = [
        film("Big Buck Bunny", 2008, "Big.Buck.Bunny.2008.1080p.BluRay.x264-OPEN"),
        film("Sintel", 2010, "Sintel.2010.720p.WEB-DL.mkv"),
        episode("Pioneer One", 1, 2, "Pioneer.One.S01E02.720p.mkv"),
    ]

    ns.build_raw(entries)

    assert keep.read_text() == "untouched"
    assert not stale.exists()
    for entry in entries:
        made = scratch / "Raw" / ns.layout(entry)
        assert made.is_file() and made.stat().st_size > 0
        assert made.stat().st_mode & 0o777 == 0o644
        assert made.parent.stat().st_mode & 0o777 == 0o755


# --- draft_label ---------------------------------------------------------------------


def test_draft_label_of_a_film_takes_the_title_and_the_year(ns: ModuleType) -> None:
    assert ns.draft_label("Some.Film.2019.1080p.WEB-DL.x264-GRP", "film") == {
        "title": "Some Film",
        "year": 2019,
    }
    assert ns.draft_label("[Grp] Some Film (2019) [1080p].mkv", "film") == {
        "title": "Some Film",
        "year": 2019,
    }


def test_draft_label_of_a_film_with_a_year_in_its_title_uses_the_release_year(
    ns: ModuleType,
) -> None:
    label = ns.draft_label("Made.Up.Saga.2049.2017.IMAX.1080p.WEB-DL.mkv", "film")
    assert label == {"title": "Made Up Saga 2049", "year": 2017}


def test_draft_label_of_a_film_without_a_year_is_none(ns: ModuleType) -> None:
    assert ns.draft_label("Some.Film.1080p.WEB-DL.x264-GRP", "film") is None
    assert ns.draft_label("Some.Film.1850.1080p", "film") is None


def test_draft_label_of_an_episode_reads_season_and_episode(ns: ModuleType) -> None:
    assert ns.draft_label("Some.Show.S02E03.720p.HDTV.mkv", "episode") == {
        "series": "Some Show",
        "season": 2,
        "episode": 3,
    }


def test_draft_label_of_an_absolute_numbered_episode_is_season_one(ns: ModuleType) -> None:
    assert ns.draft_label("[Grp] Some Show - 05 (1080p) [ABCD1234].mkv", "episode") == {
        "series": "Some Show",
        "season": 1,
        "episode": 5,
    }


def test_draft_label_of_a_season_pack_has_no_episode(ns: ModuleType) -> None:
    assert ns.draft_label("Some.Show.S01.COMPLETE.720p.WEB.x264-GRP", "episode") == {
        "series": "Some Show",
        "season": 1,
        "episode": None,
    }


def test_draft_label_of_an_episode_drops_a_trailing_year_from_the_series(ns: ModuleType) -> None:
    label = ns.draft_label("Some.Show.2022.S01E01.1080p.mkv", "episode")
    assert label is not None and label["series"] == "Some Show"


def test_draft_label_of_an_unreadable_episode_is_none(ns: ModuleType) -> None:
    assert ns.draft_label("Just.A.Name.720p.mkv", "episode") is None


# --- truth_from_text and the label answers -------------------------------------------


def test_truth_from_text_reads_the_two_shapes(ns: ModuleType) -> None:
    assert ns.truth_from_text("film", "Some Film | 2019") == {"title": "Some Film", "year": 2019}
    assert ns.truth_from_text("episode", "Some Show|2|3") == {
        "series": "Some Show",
        "season": 2,
        "episode": 3,
    }


@pytest.mark.parametrize(
    ("kind", "text"),
    [("film", "only a title"), ("film", "T|year"), ("episode", "S|1"), ("episode", "|1|2")],
)
def test_truth_from_text_refuses_a_malformed_answer(ns: ModuleType, kind: str, text: str) -> None:
    with pytest.raises(ValueError):
        ns.truth_from_text(kind, text)


def test_apply_answer_accepts_replaces_drops_and_quits(ns: ModuleType) -> None:
    entry = {"name": "n", "kind": "film", "truth": None, "confirmed": False,
             "draft": {"title": "T", "year": 2000}}
    assert ns.apply_answer(entry, "") == "next"
    assert entry["truth"] == {"title": "T", "year": 2000} and entry["confirmed"] is True

    other = {"name": "n", "kind": "film", "truth": None, "confirmed": False, "draft": None}
    assert ns.apply_answer(other, "") == "again"  # no draft to accept
    assert ns.apply_answer(other, "U|1999") == "next"
    assert other["truth"] == {"title": "U", "year": 1999} and other["confirmed"] is True

    assert ns.apply_answer({"kind": "film"}, "x") == "drop"
    assert ns.apply_answer({"kind": "film"}, "q") == "quit"
    assert ns.apply_answer({"kind": "film"}, "nonsense") == "again"


def test_apply_answer_refuses_an_incomplete_season_pack_draft(ns: ModuleType) -> None:
    entry = {"name": "n", "kind": "episode", "truth": None, "confirmed": False,
             "draft": {"series": "S", "season": 1, "episode": None}}
    assert ns.apply_answer(entry, "") == "again"
    assert entry["confirmed"] is False


# --- pattern_of ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        ({"name": "Some.Show.S02E03.720p.mkv", "kind": "episode"}, "flat episode file"),
        ({"name": "Some.Show.S01.COMPLETE.720p", "kind": "episode"}, "season pack"),
        (
            {"name": "Some.Show.S01.720p", "kind": "episode", "inner": "Some.Show.S01E01.mkv"},
            "season pack",
        ),
        (
            {"name": "[Grp] Some Show - 05 (1080p) [ABCD1234].mkv", "kind": "episode"},
            "absolute episode number",
        ),
        ({"name": "[Grp] Some Film (2019).mkv", "kind": "film"}, "bracket group tag"),
        (
            film("Made Up Saga 2049", 2017, "Made.Up.Saga.2049.2017.1080p.WEB-DL"),
            "year in title",
        ),
        ({"name": "Some.Film.2019.1080p.WEB-DL.x264-GRP", "kind": "film"}, "plain"),
    ],
)
def test_pattern_of_names_the_shape(ns: ModuleType, entry: dict, expected: str) -> None:
    assert ns.pattern_of(entry) == expected
    assert ns.pattern_of(entry) in ns.PATTERNS


# --- parse_queries -------------------------------------------------------------------


def test_parse_queries_reads_film_and_serie_lines(ns: ModuleType) -> None:
    assert ns.parse_queries("film: A\nserie: B\n\n# note\n") == [("film", "A"), ("serie", "B")]
    assert ns.parse_queries("  film:  Big Buck Bunny  \n") == [("film", "Big Buck Bunny")]


@pytest.mark.parametrize("text", ["movie: A", "film A", "film:", "serie:   "])
def test_parse_queries_refuses_an_unknown_prefix_or_an_empty_query(
    ns: ModuleType, text: str
) -> None:
    with pytest.raises(ns.Fail) as caught:
        ns.parse_queries(text)
    assert caught.value.step == "queries"


# --- capture is names only -----------------------------------------------------------


def test_the_script_never_names_the_download_endpoint(ns: ModuleType) -> None:
    source = (SCRIPTS / "name_scan.py").read_text(encoding="utf-8")
    assert "/api/" + "download" not in source


def test_searches_are_spaced_inside_the_portal_limit(ns: ModuleType) -> None:
    assert 60 / ns.SEARCH_SPACING <= 10  # SEC-05: 10 searches per minute
    assert "time.sleep" in (SCRIPTS / "name_scan.py").read_text(encoding="utf-8")


# --- the report privacy contract (D-101) ---------------------------------------------

FAKE_REAL = [
    ("Zorblax.Quantum.Heist.2031.1080p.WEB-DL.x264-GRP", "film", "plain", "identified"),
    ("[Frobnitz] Quibble Chronicles (2044) [1080p].mkv", "film", "bracket group tag", "wrong title"),
    ("Mumblecore.Waterfall.S02E03.720p.HDTV.mkv", "episode", "flat episode file", "unidentified"),
    ("[Wibble] Gnarlybeast Academy - 05 (1080p) [ABCD1234].mkv", "episode",
     "absolute episode number", "unidentified"),
]


def fake_doc(source: str, rows: list[dict]) -> dict:
    return {"source": source, "verdict": None, "rows": rows}


def fake_real_results(ns: ModuleType) -> dict:
    rows = [
        {
            "name": name,
            "kind": kind,
            "expected": "exp " + name[:12],
            "matched": "got " + name[:12],
            "result": result,
            "pattern": pattern,
        }
        for name, kind, pattern, result in FAKE_REAL
    ]
    doc = fake_doc("real", rows)
    doc["verdict"] = ns.verdict(rows)
    return doc


def sample_results(ns: ModuleType) -> dict:
    entries = json.loads(ns.SAMPLE.read_text(encoding="utf-8"))
    rows = [
        {
            "name": e["name"],
            "kind": e["kind"],
            "expected": ns.expected_text(e),
            "matched": ns.expected_text(e),
            "result": "identified",
            "pattern": ns.pattern_of(e),
        }
        for e in entries
    ]
    doc = fake_doc("sample", rows)
    doc["verdict"] = ns.verdict(rows)
    return doc


def fake_corpus() -> list[dict]:
    return [{"name": n, "kind": k} for n, k, _, _ in FAKE_REAL]


def test_render_report_carries_no_real_name_in_any_form(ns: ModuleType) -> None:
    real = fake_real_results(ns)
    text = ns.render_report(real, sample_results(ns))
    folded = ns.normalise(text)

    for name, kind, _, _ in FAKE_REAL:
        assert name not in text
        assert ns.normalise(name) not in folded
        draft = ns.draft_label(name, kind)
        title = (draft or {}).get("title") or (draft or {}).get("series") or ""
        if len(title) >= 8:
            assert ns.normalise(title) not in folded
    assert ns.validate_report(text, fake_corpus()) == []


def test_render_report_has_the_headings_the_synthetic_names_and_the_counts(ns: ModuleType) -> None:
    real = fake_real_results(ns)
    text = ns.render_report(real, sample_results(ns))

    assert text.startswith("# Naming scan test (NAME-01)\n")
    for heading in ("## Real corpus", "## Synthetic sample", "## Decision"):
        assert f"\n{heading}\n" in text
    assert "Pioneer.One.S01E02.720p.WEB.x264-VODO.mkv" in text
    assert "Meets the D-92 bar: no" in text
    assert "flat episode file" in text  # failure classes are counts only
    assert "Pending: recorded in .planning/PROJECT.md after the real scan (plan 03-09)." in text


def test_render_report_without_real_results_says_not_run_yet(ns: ModuleType) -> None:
    text = ns.render_report(None, sample_results(ns))
    assert "\nNot run yet.\n" in text
    assert ns.validate_report(text, None) == []


def test_render_report_prints_the_decision_when_given(ns: ModuleType) -> None:
    text = ns.render_report(None, sample_results(ns), decision="The rename step wins.")
    assert "The rename step wins." in text
    assert "Pending:" not in text


def test_validate_report_flags_a_missing_heading(ns: ModuleType) -> None:
    text = ns.render_report(None, sample_results(ns)).replace("## Decision", "## Something else")
    problems = ns.validate_report(text, None)
    assert any("## Decision" in p for p in problems)


def test_validate_report_flags_a_real_name_without_echoing_it(ns: ModuleType) -> None:
    base = ns.render_report(None, sample_results(ns))
    for leaked in (
        FAKE_REAL[0][0],
        "zorblax quantum heist",  # the name with its punctuation folded
        "Zorblax-Quantum-Heist",
    ):
        problems = ns.validate_report(base + "\n" + leaked + "\n", fake_corpus())
        assert problems, leaked
        assert not any("Zorblax" in p for p in problems)


def test_validate_report_ignores_a_corpus_name_that_is_a_published_sample_name(
    ns: ModuleType,
) -> None:
    text = ns.render_report(None, sample_results(ns))
    corpus = [{"name": "Sintel.2010.720p.WEB-DL.AAC.H264.mkv", "kind": "film"}]
    assert ns.validate_report(text, corpus) == []


def test_the_committed_report_is_valid(ns: ModuleType) -> None:
    path = ns.REPORT
    if not path.exists():
        pytest.skip("docs/naming-scan.md is committed later in this plan")
    assert ns.validate_report(path.read_text(encoding="utf-8"), None) == []


# --- a sample run and a report never clobber the real evidence (WR-04) -----------------


@pytest.fixture
def workdir(ns: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for attr, name in (
        ("RESULTS", "results.json"),
        ("SAMPLE_RESULTS", "sample-results.json"),
        ("TABLE", "table.md"),
        ("SAMPLE_TABLE", "sample-table.md"),
        ("CORPUS", "corpus.json"),
    ):
        monkeypatch.setattr(ns, attr, tmp_path / name)
    monkeypatch.setattr(ns, "build_raw", lambda entries: len(entries))
    monkeypatch.setattr(ns.js, "admin_api", lambda _base: (None, "user"))
    monkeypatch.setattr(ns, "ensure_raw_libraries", lambda _api: {})
    monkeypatch.setattr(ns.js, "wait_for_scan", lambda _api, _user: None)
    monkeypatch.setattr(ns, "settled_collect", lambda _api, _user, _libs: ({}, {}))
    return tmp_path


def run_args(ns: ModuleType, corpus: Path) -> object:
    return type("Args", (), {"corpus": str(corpus), "base": "http://x"})()


def test_a_sample_run_leaves_the_real_results_and_table_alone(
    ns: ModuleType, workdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_rows = fake_real_results(ns)["rows"]
    sample_rows = sample_results(ns)["rows"]
    real_corpus = workdir / "real-corpus.json"
    real_corpus.write_text(ns.SAMPLE.read_text(encoding="utf-8"), encoding="utf-8")

    monkeypatch.setattr(ns, "build_rows", lambda *_a: real_rows)
    assert ns.cmd_run(run_args(ns, real_corpus)) == 0
    real_text, table_text = ns.RESULTS.read_text(), ns.TABLE.read_text()
    assert json.loads(real_text)["source"] == "real"
    assert not ns.SAMPLE_RESULTS.exists()

    monkeypatch.setattr(ns, "build_rows", lambda *_a: sample_rows)
    assert ns.cmd_run(run_args(ns, ns.SAMPLE)) == 0

    assert ns.RESULTS.read_text() == real_text
    assert ns.TABLE.read_text() == table_text
    assert json.loads(ns.SAMPLE_RESULTS.read_text())["source"] == "sample"
    assert ns.SAMPLE_TABLE.exists()


def report_args(ns: ModuleType, out: Path, decision: str | None = None) -> object:
    return type(
        "Args",
        (),
        {
            "results": str(ns.RESULTS),
            "sample_results": str(ns.SAMPLE_RESULTS),
            "out": str(out),
            "decision": decision,
        },
    )()


def seed_report(ns: ModuleType, workdir: Path, decision: str) -> Path:
    ns.RESULTS.write_text(json.dumps(fake_real_results(ns)), encoding="utf-8")
    ns.SAMPLE_RESULTS.write_text(json.dumps(sample_results(ns)), encoding="utf-8")
    out = workdir / "naming-scan.md"
    assert ns.cmd_report(report_args(ns, out, decision)) == 0
    return out


def test_report_without_a_decision_keeps_the_recorded_decision(ns: ModuleType, workdir: Path) -> None:
    out = seed_report(ns, workdir, "The rename step wins, on the data above.")

    assert ns.cmd_report(report_args(ns, out)) == 0

    text = out.read_text()
    assert "The rename step wins, on the data above." in text
    assert "Pending:" not in text
    assert "Meets the D-92 bar: no" in text


def test_report_with_a_decision_replaces_the_recorded_one(ns: ModuleType, workdir: Path) -> None:
    out = seed_report(ns, workdir, "Old decision.")

    assert ns.cmd_report(report_args(ns, out, "New decision.")) == 0

    text = out.read_text()
    assert "New decision." in text and "Old decision." not in text


def test_report_refuses_to_replace_real_counts_with_not_run_yet(ns: ModuleType, workdir: Path) -> None:
    out = seed_report(ns, workdir, "Keep me.")
    before = out.read_text()
    ns.RESULTS.unlink()  # no real run on hand any more

    with pytest.raises(ns.Fail) as caught:
        ns.cmd_report(report_args(ns, out))

    assert caught.value.step == "report"
    assert out.read_text() == before


def test_report_of_a_fresh_file_still_says_not_run_yet_and_pending(ns: ModuleType, workdir: Path) -> None:
    ns.SAMPLE_RESULTS.write_text(json.dumps(sample_results(ns)), encoding="utf-8")
    out = workdir / "fresh.md"

    assert ns.cmd_report(report_args(ns, out)) == 0

    text = out.read_text()
    assert "\nNot run yet.\n" in text and "Pending:" in text
