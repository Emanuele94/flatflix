"""Docs contract (INFRA-04, JFIN-01): the admin guide for Jellyfin and the TV stays true.

docs/setup.md is the admin's script for the real-TV session, so three things are pinned here:
the exact copy the UI-SPEC fixed, every `python3 scripts/<name>.py <subcommand>` it prints
(the script and the subcommand must exist), and the privacy rule (placeholders only, no MAC
address). The helpers are pure functions over text so a mutated text proves each check has teeth.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(
    subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent,
    ).stdout.strip()
)
SETUP = ROOT / "docs" / "setup.md"
SCRIPTS = ROOT / "scripts"

SECTION = "## Jellyfin and the TV"
SAME_ADDRESS = "### Keep the laptop on the same address"
SIGN_IN = "Open /jellyfin on the PC, choose Manual Login, sign in as admin."
RESTART_CHECK = (
    "Restart the laptop and the router. The TV must still open the same address without any change."
)
RESET_WARNING = "This removes all Jellyfin settings and watch history. It cannot be undone."
RESET_COMMAND = "docker compose stop jellyfin && sudo rm -rf jellyfin/config jellyfin/cache"
ADDRESS_IP_FORM = "On the TV browser, open http://<laptop-ip>/jellyfin."
ADDRESS_BOTH_FORM = (
    "On the TV browser, open http://flatflix.local/jellyfin. If the TV cannot find that name, "
    "use http://<laptop-ip>/jellyfin instead."
)
TROUBLE_SYMPTOMS = (
    "Jellyfin page is blank or has no styles",
    "The TV cannot open the .local name",
    "Jellyfin says it is starting",
    "/jellyfin shows 'Jellyfin is not available right now'",
    "The household account is locked",
)
SECTIONS_IN_ORDER = (
    "### First start",
    "### The household account",
    "### Streaming bitrate limit",
    SAME_ADDRESS,
    "### A name instead of the address (.local)",
    "### TV compatibility test",
    "### Naming scan test",
    "### Reset Jellyfin",
)

_COMMAND = re.compile(r"python3 (?:scripts/)?([A-Za-z0-9_]+)\.py ([a-z][a-z0-9-]*)")
_ADD_PARSER_LITERAL = re.compile(r"""add_parser\(\s*["']([\w-]+)["']""")
_ADD_PARSER_NAME = re.compile(r"add_parser\(\s*([A-Za-z_]\w*)\s*[,)]")
_MAC_COLON = re.compile(r"(?<![0-9A-Fa-f:-])[0-9A-Fa-f]{2}([:-])(?:[0-9A-Fa-f]{2}\1){4}[0-9A-Fa-f]{2}(?![0-9A-Fa-f:-])")
_MAC_DOTTED = re.compile(r"(?<![0-9A-Fa-f.])[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}(?![0-9A-Fa-f.])")
_URL = re.compile(r"https?://[^\s)`'\"<>]*(?:<[a-z-]+>[^\s)`'\"]*)?")


def section(text: str, heading: str) -> str:
    """The body under `heading`, up to the next heading of the same or a higher level."""
    level = len(heading) - len(heading.lstrip("#"))
    lines = text.splitlines()
    try:
        start = lines.index(heading)
    except ValueError:
        return ""
    body = []
    for line in lines[start + 1 :]:
        match = re.match(r"(#+) ", line)
        if match and len(match.group(1)) <= level:
            break
        body.append(line)
    return "\n".join(body)


def documented_commands(text: str) -> list[tuple[str, str]]:
    """Every `python3 scripts/<name>.py <subcommand>` pair in text, in order."""
    return [(name, sub) for name, sub in _COMMAND.findall(text)]


def defined_subcommands(script_text: str) -> set[str]:
    """The subcommand names a script passes to add_parser (literals and loop variables)."""
    names = set(_ADD_PARSER_LITERAL.findall(script_text))
    for variable in _ADD_PARSER_NAME.findall(script_text):
        loop = re.search(rf"for {variable} in \(([^)]*)\)", script_text)
        if loop:
            names.update(re.findall(r"""["']([\w-]+)["']""", loop.group(1)))
    return names


def find_macs(text: str) -> list[str]:
    """Every MAC address (colon, dash or dotted form) in text."""
    return [m.group(0) for m in _MAC_COLON.finditer(text)] + [
        m.group(0) for m in _MAC_DOTTED.finditer(text)
    ]


def missing_commands(text: str, scripts_dir: Path = SCRIPTS) -> list[str]:
    """Documented commands whose script or subcommand does not exist."""
    problems = []
    for name, sub in documented_commands(text):
        script = scripts_dir / f"{name}.py"
        if not script.is_file():
            problems.append(f"{name}.py does not exist")
        elif sub not in defined_subcommands(script.read_text(encoding="utf-8")):
            problems.append(f"{name}.py has no subcommand {sub}")
    return problems


def bad_addresses(text: str) -> list[str]:
    """URLs that name anything but a placeholder, the loopback address or the household name."""
    allowed = ("<laptop-ip>", "<laptop-name>.local", "127.0.0.1", "flatflix.local", "localhost")
    return [url for url in _URL.findall(text) if not any(url.startswith(f"http://{a}") for a in allowed)]


def setup_text() -> str:
    return SETUP.read_text(encoding="utf-8")


# --- the copy ---------------------------------------------------------------------------


def test_setup_has_one_jellyfin_section_and_one_same_address_heading():
    lines = setup_text().splitlines()
    assert lines.count(SECTION) == 1
    assert lines.count(SAME_ADDRESS) == 1


def test_the_subsections_are_all_there_and_in_order():
    body = section(setup_text(), SECTION)
    positions = [body.splitlines().index(heading) for heading in SECTIONS_IN_ORDER]
    assert positions == sorted(positions)


def test_the_jellyfin_section_follows_phone_access_and_that_section_points_to_it():
    text = setup_text()
    assert text.index("## Phone access (D-04)") < text.index(SECTION) < text.index("## Admin tasks")
    assert "A stable address (DHCP\n  reservation on the router) comes in Phase 3." not in text
    assert "Keep the laptop on the same address" in section(text, "## Phone access (D-04)")


def test_the_household_address_line_is_one_of_the_two_ui_spec_forms():
    body = section(setup_text(), SECTION)
    assert (ADDRESS_IP_FORM in body) != (ADDRESS_BOTH_FORM in body)


def test_the_exact_sentences_are_present_once():
    text = setup_text()
    for sentence in (SIGN_IN, RESTART_CHECK, RESET_WARNING):
        assert text.count(sentence) == 1, sentence


def test_the_reset_warning_comes_before_the_line_holding_the_removal_command():
    lines = setup_text().splitlines()
    warning = next(i for i, line in enumerate(lines) if RESET_WARNING in line)
    command = next(i for i, line in enumerate(lines) if "rm -rf jellyfin/config" in line)
    assert warning < command
    assert RESET_COMMAND in lines[command]
    assert "jellyfin/config jellyfin/cache" in lines[command]
    assert "rm -rf" not in "\n".join(lines[:warning] + lines[command + 1 :])


def test_the_restart_check_ends_the_same_address_section():
    body = section(setup_text(), SAME_ADDRESS)
    assert body.strip().splitlines()[-1].endswith(RESTART_CHECK)


def test_the_same_address_section_names_the_reservation_and_the_windows_settings():
    body = section(setup_text(), SAME_ADDRESS)
    for needle in (
        "<laptop-ip>",
        "<mac-address>",
        "random hardware addresses",
        "sleep",
        "Start Docker Desktop when you sign in to your computer",
    ):
        assert needle in body, needle


def test_the_local_ladder_documents_the_phone_test_and_avahi():
    body = section(setup_text(), "### A name instead of the address (.local)")
    for needle in (
        "<laptop-name>.local",
        "avahi-daemon",
        "host-name=flatflix",
        "allow-interfaces=<lan-nic>",
        "5353/udp",
        "avahi-resolve -n flatflix.local",
    ):
        assert needle in body, needle


def test_the_bitrate_section_covers_the_tv_client_setting():
    body = section(setup_text(), "### Streaming bitrate limit")
    for needle in (
        "JELLYFIN_MAX_BITRATE_MBPS",
        "jellyfin_setup.py measure --base http://<laptop-ip>/jellyfin",
        "jellyfin_setup.py cap --mbps",
        "Maximum streaming bitrate",
        "Dashboard > Playback > Streaming",
    ):
        assert needle in body, needle


def test_the_household_section_names_the_account_and_quick_connect():
    body = section(setup_text(), "### The household account")
    for needle in ("household", "JELLYFIN_HOUSEHOLD_PASSWORD", "Quick Connect", "locks"):
        assert needle in body, needle


def test_first_start_runs_the_provisioning_commands_in_order():
    body = section(setup_text(), "### First start")
    ordered = [
        "dev_env.py",
        "init-host-dirs.sh",
        "docker compose up -d --wait && python3 scripts/jellyfin_setup.py setup --no-scan",
        "make_compat_clips.py sources",
        "make_compat_clips.py library",
        "jellyfin_setup.py setup\n",
        "jellyfin_setup.py check",
        SIGN_IN,
    ]
    positions = [body.index(item) for item in ordered]
    assert positions == sorted(positions)


def test_the_troubleshooting_table_holds_the_five_jellyfin_symptoms():
    rows = [
        line for line in section(setup_text(), "## Troubleshooting").splitlines() if line.startswith("|")
    ]
    cells = [row.split("|")[1].strip().replace("`", "") for row in rows]
    for symptom in TROUBLE_SYMPTOMS:
        assert symptom in cells, symptom
    assert "Phone cannot open the page" in cells  # the existing rows stay


def test_every_existing_section_is_still_there():
    lines = setup_text().splitlines()
    for heading in (
        "## Prerequisites",
        "## First run",
        "## Phone access (D-04)",
        "## Admin tasks",
        "## Where files go",
        "## Upgrading from Phase 2",
        "## Safety check of finished downloads",
        "## Troubleshooting",
    ):
        assert heading in lines, heading


# --- the commands -----------------------------------------------------------------------


def test_documented_commands_finds_each_pair():
    text = "run `python3 scripts/tv_gate.py watch` then python3 jellyfin_setup.py cap --mbps 90"
    assert documented_commands(text) == [("tv_gate", "watch"), ("jellyfin_setup", "cap")]


def test_defined_subcommands_reads_literals_and_loop_variables():
    source = (
        'sub.add_parser("setup", parents=[common])\n'
        "for command in (\"sources\", 'library'):\n"
        "    one = sub.add_parser(command)\n"
    )
    assert defined_subcommands(source) == {"setup", "sources", "library"}


def test_every_documented_script_command_exists():
    text = setup_text()
    commands = documented_commands(text)
    assert len(commands) >= 15, "the Jellyfin section documents the scripts, parsing found too few"
    assert missing_commands(text) == []


def test_every_script_subcommand_of_the_four_helpers_is_documented_or_deliberately_left_out():
    documented = {pair for pair in documented_commands(setup_text())}
    expected = {
        ("jellyfin_setup", "setup"),
        ("jellyfin_setup", "check"),
        ("jellyfin_setup", "measure"),
        ("jellyfin_setup", "cap"),
        ("make_compat_clips", "sources"),
        ("make_compat_clips", "library"),
        ("make_compat_clips", "clips"),
        ("tv_gate", "watch"),
        ("tv_gate", "selftest"),
        ("tv_gate", "render"),
        ("tv_gate", "validate"),
        ("tv_gate", "verdict"),
        ("tv_gate", "forget"),
        ("name_scan", "capture"),
        ("name_scan", "label"),
        ("name_scan", "run"),
        ("name_scan", "report"),
    }
    assert expected <= documented, sorted(expected - documented)


def test_a_made_up_subcommand_is_reported():
    mutated = setup_text() + "\npython3 scripts/jellyfin_setup.py nuke\n"
    assert "jellyfin_setup.py has no subcommand nuke" in missing_commands(mutated)


def test_a_missing_script_is_reported():
    mutated = setup_text() + "\npython3 scripts/not_there.py run\n"
    assert "not_there.py does not exist" in missing_commands(mutated)


# --- privacy ----------------------------------------------------------------------------


def test_no_file_under_docs_contains_a_mac_address():
    for path in sorted((ROOT / "docs").rglob("*.md")):
        assert find_macs(path.read_text(encoding="utf-8")) == [], path.name


def test_the_mac_scan_catches_every_common_form():
    for sample in ("aa:bb:cc:dd:ee:ff", "AA-BB-CC-DD-EE-FF", "aabb.ccdd.eeff"):
        assert find_macs(f"reserve {sample} on the router") == [sample]
    assert find_macs("reserve <mac-address> on the router") == []
    assert find_macs("time 12:30:45 and sha 0123456789abcdef") == []


def test_the_jellyfin_section_uses_placeholders_for_every_address():
    body = section(setup_text(), SECTION)
    assert bad_addresses(body) == []
    assert "<laptop-ip>" in body and "<mac-address>" in body and "<lan-nic>" in body


def test_the_address_scan_catches_a_real_looking_address():
    sample = "open http://" + ".".join(["198", "51", "100", "7"]) + "/jellyfin"
    assert bad_addresses(sample) != []
    assert bad_addresses("open http://<laptop-ip>/jellyfin and http://127.0.0.1/") == []


# --- PROJECT.md (D-80..D-100) ----------------------------------------------------------

PROJECT = ROOT / ".planning" / "PROJECT.md"
_DEVICE_ID = re.compile(
    r"\b(?:serial(?:[ _-]?(?:number|no))?|esn|device[ _-]?id)\b[ \t]*[:=|][ \t]*\S", re.IGNORECASE
)


def key_decisions(text: str) -> list[list[str]]:
    """The rows of the Key Decisions table as [decision, rationale, outcome] cells."""
    rows = []
    for line in section(text, "## Key Decisions").splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells[0] in ("Decision",) or set(cells[0]) <= {"-"}:
            continue
        rows.append(cells)
    return rows


def find_device_ids(text: str) -> list[str]:
    """Lines where a serial number, ESN or device id is followed by a value."""
    return [line for line in text.splitlines() if _DEVICE_ID.search(line)]


def project_rows() -> list[list[str]]:
    return key_decisions(PROJECT.read_text(encoding="utf-8"))


def row_starting(prefix: str) -> list[str]:
    matches = [row for row in project_rows() if row[0].startswith(prefix)]
    assert len(matches) == 1, f"expected one row starting {prefix!r}, found {len(matches)}"
    return matches[0]


def test_key_decisions_parses_the_table_into_three_cells():
    rows = project_rows()
    assert len(rows) >= 20
    assert all(len(row) == 3 for row in rows)
    assert row_starting("Build the qBittorrent portal first")[2].startswith("Decided")


def test_no_decision_is_still_pending_for_phase_3():
    rows = project_rows()
    assert not [row for row in rows if "Pending (Phase 3)" in row[2]]
    assert not [row for row in rows if "Pending (Phase 3 decides" in row[2]]


def test_the_naming_decision_is_recorded():
    outcome = row_starting("Who puts downloads")[2]
    assert "Decided (Phase 3, NAME-01)" in outcome
    assert "[docs/naming-scan.md](../docs/naming-scan.md)" in outcome
    assert "Phase 4 implements" in outcome
    assert "Pending" not in outcome


def test_the_naming_row_link_points_at_a_file_that_exists():
    link = re.search(r"\]\((\.\./docs/naming-scan\.md)\)", PROJECT.read_text(encoding="utf-8"))
    assert link and (PROJECT.parent / link.group(1)).resolve().is_file()


def test_the_real_corpus_is_reported():
    text = (ROOT / "docs" / "naming-scan.md").read_text(encoding="utf-8")
    real = section(text, "## Real corpus")
    assert "Not run yet." not in real
    for label in ("identified", "unidentified", "wrong title"):
        assert re.search(rf"^\| {label} \| \d+ \|$", real, re.MULTILINE), label
    assert re.search(r"^Meets the D-92 bar: (yes|no)$", real, re.MULTILINE)
    decision = section(text, "## Decision").strip()
    assert decision and not decision.startswith("Pending")
    assert "Not run yet." not in decision


def test_the_shared_user_row_names_household_the_hidden_admin_and_prof_01():
    row = row_starting("One shared Jellyfin user")
    outcome = row[2]
    for needle in ("household", "hidden", "admin", "PROF-01", "Decided", "D-94"):
        assert needle in outcome, needle


def test_the_language_row_names_english_audio_and_smart_english_subtitles():
    outcome = row_starting("Default audio and subtitle language")[2]
    for needle in ("English", "Smart", "forced", "Decided", "D-95"):
        assert needle in outcome, needle


def test_the_port_map_row_records_jellyfin_behind_caddy():
    outcome = row_starting("Laptop port map")[2]
    for needle in ("/jellyfin", "D-80", "8096", "D-82", "/tv", "Phase 5"):
        assert needle in outcome, needle


def test_the_single_origin_row_says_it_was_built_in_phase_3():
    assert "Built in Phase 3" in row_starting("Jellyfin + Caddy single origin")[2]


def test_the_new_rows_record_tmdb_the_admin_password_and_the_compatibility_doc():
    tmdb = row_starting("TheMovieDb lookup by the portal backend")
    assert "TMDB_API_KEY" in tmdb[1] and "D-93" in tmdb[2] and "Phase 4" in tmdb[2]
    exposure = row_starting("Jellyfin admin password visible in the backend container")
    assert "D-100" in exposure[2] and "Phase 5" in exposure[2]
    matrix = row_starting("TV compatibility matrix and go/no-go verdict")
    assert "[docs/tv-compatibility.md](../docs/tv-compatibility.md)" in matrix[2]
    assert "Pending (Phase 3 TV session)" in matrix[2]


def test_the_compatibility_link_points_at_a_file_that_exists():
    link = re.search(r"\]\((\.\./docs/tv-compatibility\.md)\)", PROJECT.read_text(encoding="utf-8"))
    assert link and (PROJECT.parent / link.group(1)).resolve().is_file()


def test_the_footer_names_phase_3_and_a_date():
    last = PROJECT.read_text(encoding="utf-8").strip().splitlines()[-1]
    assert "Phase 3" in last and re.search(r"2026-10-\d\d", last)


def test_the_new_rows_hold_no_secret_or_address():
    text = PROJECT.read_text(encoding="utf-8")
    assert find_macs(text) == [] and find_device_ids(text) == []


def test_the_compatibility_docs_hold_no_mac_address_and_no_device_id_value():
    for name in ("tv-compatibility.md", "naming-scan.md"):
        text = (ROOT / "docs" / name).read_text(encoding="utf-8")
        assert find_macs(text) == [], name
        assert find_device_ids(text) == [], name


def test_the_device_id_scan_catches_each_separator_and_ignores_prose():
    for sample in (
        "Serial: ABC123",
        "serial number = 99X",
        "| Device ID | 7f3a |",
        "ESN: NFANDROID",
        "device_id=0123",
    ):
        assert find_device_ids(sample) == [sample], sample
    assert find_device_ids("Forbidden: serial number, device ID, ESN, MAC address.") == []
    assert find_device_ids("The serial is never recorded") == []
