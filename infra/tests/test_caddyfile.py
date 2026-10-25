"""Docker-free invariants for web/Caddyfile: the portal policy and the Jellyfin route (INFRA-03).

Caddy cannot override a site-level header from a route, so the portal's
Content-Security-Policy is scoped with a matcher and pinned here byte for byte.
The checks are pure functions over the Caddyfile text, so the mutation tests can
prove each one catches the edit it exists for.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest


def _repo_root() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent,
    )
    return Path(out.stdout.strip())


ROOT = _repo_root()

# The portal policy as it was before Jellyfin arrived. It must not change.
PORTAL_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
    "form-action 'self'"
)
JELLYFIN_DOWN_TEXT = "Jellyfin is not available right now. Ask the admin to check the server."
MATCHER_LINE = "@notjellyfin not path /jellyfin /jellyfin/*"
JELLYFIN_DOWN_MATCHER = "@jellyfin_down path /jellyfin /jellyfin/*"
RESPOND_LINE = f'respond @jellyfin_down "{JELLYFIN_DOWN_TEXT}" {{http.error.status_code}}'


@pytest.fixture(scope="module")
def caddyfile() -> str:
    return (ROOT / "web" / "Caddyfile").read_text(encoding="utf-8")


def site_lines(text: str) -> list[str]:
    """Stripped, non-comment lines at brace depth 1 (the site's own level)."""
    lines = []
    depth = 0
    for line in text.splitlines():
        stripped = line.strip()
        if depth == 1 and stripped and not stripped.startswith("#"):
            lines.append(stripped)
        depth += line.count("{") - line.count("}")
    return lines


def depth1_blocks(text: str) -> list[str]:
    """Each depth-1 block (a line ending in an opening brace, through its closing brace)."""
    blocks: list[list[str]] = []
    current: list[str] | None = None
    depth = 0
    for line in text.splitlines():
        if current is None and depth == 1 and line.strip().endswith("{"):
            current = []
            blocks.append(current)
        if current is not None:
            current.append(line)
        depth += line.count("{") - line.count("}")
        if current is not None and depth == 1:
            current = None
    return ["\n".join(block) for block in blocks]


def _code_lines(block: str) -> list[str]:
    return [
        line.strip()
        for line in block.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def portal_csp_violations(text: str) -> list[str]:
    """Every way the scoped portal policy differs from the pinned one, not just the first."""
    violations = []
    lines = site_lines(text)
    if lines.count(MATCHER_LINE) != 1:
        violations.append(f"the matcher line {MATCHER_LINE!r} must appear exactly once")
    scoped = [line for line in lines if line.startswith("header @notjellyfin Content-Security")]
    if len(scoped) != 1:
        violations.append("expected exactly one 'header @notjellyfin Content-Security-Policy' line")
    else:
        match = re.fullmatch(r'header @notjellyfin Content-Security-Policy "([^"]*)"', scoped[0])
        value = match.group(1) if match else ""
        if value != PORTAL_CSP:
            violations.append("the portal policy differs from the pinned PORTAL_CSP")
        for token in ("unsafe-inline", "unsafe-eval"):
            if token in value:
                violations.append(f"the portal policy contains {token}")
    if any(re.match(r"header\s+Content-Security-Policy", line) for line in lines):
        violations.append("a site-level header sets a policy without the @notjellyfin matcher")
    header_blocks = [b for b in depth1_blocks(text) if b.lstrip().startswith("header {")]
    if len(header_blocks) != 1:
        violations.append("expected exactly one depth-1 'header {' block")
    else:
        code = "\n".join(_code_lines(header_blocks[0]))
        if "Content-Security-Policy" in code:
            violations.append("the site header block sets a Content-Security-Policy")
        for line in (
            "X-Content-Type-Options nosniff",
            "Referrer-Policy no-referrer",
            "X-Frame-Options DENY",
            "-Server",
        ):
            if line not in code.splitlines():
                violations.append(f"the site header block lost {line!r}")
    return violations


def jellyfin_route_violations(text: str) -> list[str]:
    """Every way the /jellyfin route differs from the decided contract."""
    violations = []
    blocks = depth1_blocks(text)
    if any(line.startswith("handle_path") for line in _code_lines(text)):
        violations.append("handle_path strips the prefix; Jellyfin's BaseURL needs it kept")
    routes = [b for b in blocks if b.lstrip().startswith("handle /jellyfin/* {")]
    if len(routes) != 1:
        violations.append("expected exactly one 'handle /jellyfin/* {' block")
    else:
        code = _code_lines(routes[0])
        if "reverse_proxy jellyfin:8096" not in code:
            violations.append("the route does not reverse_proxy jellyfin:8096")
        for word in ("strip_prefix", "header_down", "handle_path"):
            if any(word in line for line in code):
                violations.append(f"the route uses {word}")
        policies = re.findall(r'^header Content-Security-Policy "([^"]*)"$', "\n".join(code), re.MULTILINE)
        if len(policies) != 1:
            violations.append("expected exactly one Content-Security-Policy header in the route")
        else:
            policy = policies[0]
            for required in ("'wasm-unsafe-eval'", "object-src 'none'", "frame-ancestors 'none'"):
                if required not in policy:
                    violations.append(f"the Jellyfin policy lacks {required}")
            for directive in policy.split(";"):
                for source in directive.split()[1:]:
                    if source in ("https:", "http:", "*") or "://" in source:
                        violations.append(f"the Jellyfin policy allows the source {source!r}")
    if "redir /jellyfin /jellyfin/ 308" not in site_lines(text):
        violations.append("the redir /jellyfin /jellyfin/ 308 line is missing")
    errors = [b for b in blocks if b.lstrip().startswith("handle_errors {")]
    if len(errors) != 1:
        violations.append("expected exactly one handle_errors block")
    else:
        code = _code_lines(errors[0])
        if JELLYFIN_DOWN_MATCHER not in code:
            violations.append(f"handle_errors lacks {JELLYFIN_DOWN_MATCHER!r}")
        if RESPOND_LINE not in code:
            violations.append("handle_errors lacks the exact Jellyfin-down respond line")
    return violations


# --- the real file ------------------------------------------------------------------------


def test_the_portal_policy_constant_has_no_unsafe_source():
    for token in ("unsafe-inline", "unsafe-eval", "wasm-unsafe-eval"):
        assert token not in PORTAL_CSP


def test_the_portal_policy_is_pinned_byte_for_byte(caddyfile):
    assert portal_csp_violations(caddyfile) == []
    assert f'header @notjellyfin Content-Security-Policy "{PORTAL_CSP}"' in caddyfile


def test_the_jellyfin_route_follows_the_contract(caddyfile):
    assert jellyfin_route_violations(caddyfile) == []


def test_the_tv_route_is_still_the_phase_5_stub(caddyfile):
    blocks = [b for b in depth1_blocks(caddyfile) if b.lstrip().startswith("handle /tv/*")]
    assert len(blocks) == 1
    assert 'respond "Not available yet" 404' in blocks[0]


# --- mutations: every check has teeth -----------------------------------------------------


def _replaced(text: str, old: str, new: str) -> str:
    assert text.count(old) >= 1, f"mutation target not found: {old!r}"
    return text.replace(old, new)


def _portal_with_unsafe_inline(text: str) -> str:
    return _replaced(
        text, PORTAL_CSP, PORTAL_CSP.replace("style-src 'self'", "style-src 'self' 'unsafe-inline'")
    )


def _portal_back_in_the_site_header(text: str) -> str:
    scoped = f'\theader @notjellyfin Content-Security-Policy "{PORTAL_CSP}"\n'
    moved = _replaced(text, scoped, "")
    return _replaced(moved, "\t\t-Server\n", f'\t\t-Server\n\t\tContent-Security-Policy "{PORTAL_CSP}"\n')


def _portal_matcher_removed(text: str) -> str:
    return _replaced(text, f"\t{MATCHER_LINE}\n", "")


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (_portal_with_unsafe_inline, "unsafe-inline"),
        (_portal_back_in_the_site_header, "header block"),
        (_portal_matcher_removed, "@notjellyfin"),
    ],
)
def test_a_weakened_portal_policy_is_caught(caddyfile, mutate, expected):
    violations = portal_csp_violations(mutate(caddyfile))
    assert any(expected in violation for violation in violations), violations


def _jellyfin_without_wasm(text: str) -> str:
    return _replaced(text, " 'wasm-unsafe-eval'", "")


def _jellyfin_with_https_source(text: str) -> str:
    return _replaced(text, "connect-src 'self' ws: wss:", "connect-src 'self' https: ws: wss:")


def _jellyfin_with_handle_path(text: str) -> str:
    return _replaced(text, "handle /jellyfin/* {", "handle_path /jellyfin/* {")


def _jellyfin_with_strip_prefix(text: str) -> str:
    return _replaced(
        text,
        "\t\treverse_proxy jellyfin:8096",
        "\t\turi strip_prefix /jellyfin\n\t\treverse_proxy jellyfin:8096",
    )


def _jellyfin_without_redirect(text: str) -> str:
    return _replaced(text, "\tredir /jellyfin /jellyfin/ 308\n", "")


def _jellyfin_down_text_changed(text: str) -> str:
    return _replaced(text, JELLYFIN_DOWN_TEXT, "Jellyfin is down.")


def _jellyfin_without_object_src_none(text: str) -> str:
    return _replaced(text, " object-src 'none';", "")


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (_jellyfin_without_wasm, "wasm-unsafe-eval"),
        (_jellyfin_with_https_source, "https:"),
        (_jellyfin_with_handle_path, "handle_path"),
        (_jellyfin_with_strip_prefix, "strip_prefix"),
        (_jellyfin_without_redirect, "redir"),
        (_jellyfin_down_text_changed, "handle_errors"),
        (_jellyfin_without_object_src_none, "object-src"),
    ],
)
def test_a_broken_jellyfin_route_is_caught(caddyfile, mutate, expected):
    violations = jellyfin_route_violations(mutate(caddyfile))
    assert any(expected in violation for violation in violations), violations
