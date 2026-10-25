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
