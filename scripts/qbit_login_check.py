#!/usr/bin/env python3
"""Probe the qBittorrent WebUI login from inside the qbittorrent container.

    docker compose exec -T qbittorrent python3 - < scripts/qbit_login_check.py [base-url]

Reads QBITTORRENT_USER / QBITTORRENT_PASS from the process environment, tries the
real password once and a wrong one once, and prints status codes only.
Exit 0 only when the real password is accepted and the wrong one refused.
"""

import http.client
import os
import secrets
import sys
import urllib.parse

base = sys.argv[1] if len(sys.argv) > 1 else "http://qbittorrent:8088"
parts = urllib.parse.urlsplit(base)
host, port = parts.hostname, parts.port or 80
user = os.environ["QBITTORRENT_USER"]
real = os.environ["QBITTORRENT_PASS"]


def login(password):
    conn = http.client.HTTPConnection(host, port, timeout=10)
    body = urllib.parse.urlencode({"username": user, "password": password})
    # No Referer or Origin header on purpose (qBittorrent rejects a foreign one).
    conn.request(
        "POST",
        "/api/v2/auth/login",
        body=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp = conn.getresponse()
    text = resp.read().decode("utf-8", "replace").strip()
    conn.close()
    return resp.status, text


right_status, right_body = login(real)
wrong_status, wrong_body = login("wrong-" + secrets.token_hex(6))

accepted = right_status in (200, 204) and right_body != "Fails."
refused = wrong_status == 401 or wrong_body == "Fails."

print("right password: %d" % right_status)
print("wrong password: %d" % wrong_status)
sys.exit(0 if (accepted and refused) else 1)
