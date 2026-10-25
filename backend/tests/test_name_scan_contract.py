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
