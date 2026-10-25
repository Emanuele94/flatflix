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
    return []  # RED stub


def depth1_blocks(text: str) -> list[str]:
    """Each depth-1 block (a line ending in an opening brace, through its closing brace)."""
    return []  # RED stub


def portal_csp_violations(text: str) -> list[str]:
    """Every way the scoped portal policy differs from the pinned one, not just the first."""
    return []  # RED stub


def jellyfin_route_violations(text: str) -> list[str]:
    """Every way the /jellyfin route differs from the decided contract."""
    return []  # RED stub


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
