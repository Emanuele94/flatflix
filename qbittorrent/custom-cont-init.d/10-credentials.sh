#!/usr/bin/with-contenv bash
# Provision the qBittorrent WebUI credentials from the container environment.
# Runs on every start, after the image's own init and before services start.
# Writes only the username and the PBKDF2 hash; never prints the password.
set -eu

CONF=/config/qBittorrent/qBittorrent.conf
mkdir -p /config/qBittorrent
[ -f "$CONF" ] || cp /defaults/qBittorrent.conf "$CONF"

python3 - "$CONF" <<'PY'
import base64, hashlib, os, sys

conf = sys.argv[1]
user = os.environ["QBITTORRENT_USER"]
pw = os.environ["QBITTORRENT_PASS"].encode()
salt = os.urandom(16)
key = hashlib.pbkdf2_hmac("sha512", pw, salt, 100000, 64)
line = "WebUI\\Password_PBKDF2=@ByteArray(%s:%s)" % (
    base64.b64encode(salt).decode(),
    base64.b64encode(key).decode(),
)
out = []
for l in open(conf).read().splitlines():
    if l.startswith(("WebUI\\Username=", "WebUI\\Password_PBKDF2=")):
        continue
    out.append(l)
    if l.strip() == "[Preferences]":
        out += ["WebUI\\Username=" + user, line]
open(conf, "w").write("\n".join(out) + "\n")
PY

chown abc:abc /config/qBittorrent /config/qBittorrent/qBittorrent.conf
echo "[10-credentials] WebUI credentials provisioned for the configured user"
