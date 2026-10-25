#!/usr/bin/env python3
"""Build the Jellyfin scratch library from CC-licensed Blender open movies (standard library only).

Usage:
    python3 scripts/make_compat_clips.py sources [--only NAME ...]
    python3 scripts/make_compat_clips.py library [--only NAME ...]

NAME is one of bbb, sintel, tos and pioneer (pioneer needs the sintel source).

`sources` downloads the Blender open movies into jellyfin/sources (gitignored): bbb (Big Buck Bunny
1080p, CC BY, a zip), sintel (Sintel 1080p MKV, CC BY) and tos (Tears of Steel 720p, CC BY). Each
download goes to a `.part` file, is checked against the sha256 pinned in SOURCES (a mismatch is
refused) and only then renamed into place. A source with no pin yet prints `sha256 <name> <hex>`
once, so the first verified download can be pinned in this file. An existing file whose hash
matches is kept and not downloaded again.

`library` lays the sources out under jellyfin/scratch (mounted read-only into Jellyfin) with the
names Jellyfin needs: `Movies/Title (Year)/Title (Year).ext`. Big Buck Bunny and Sintel are
hardlinked from the sources folder (a copy only on a cross-device error); Tears of Steel is
remuxed from .mov into .mkv with ffmpeg (`-map 0 -c copy`, no re-encode). Every file is written
under a `.part` name and renamed to its final name only when complete, so a scan never sees a
half-written film; run `library` again to rebuild one.

Sources come only from download.blender.org (CC-licensed open movies); no copyrighted content is
fetched or generated here. Files are 0644 and folders 0755. ffmpeg runs through argument lists,
never a shell. Output names and sizes only. Exit 3 when ffmpeg is missing.

`pioneer` (D-97) builds the series stand-ins: `TV/Pioneer One/Season 01/Pioneer One S01E01.mkv` to
S01E03, each a 60 s clip cut from the Sintel source at 120, 300 and 480 s (H.264 720p, AAC stereo
tagged language=eng, RESEARCH Pitfall 8). The files are stand-ins on purpose: the series poster,
the season and the episode plots come from TheMovieDb by name, which is what D-97 asks for. Real
episodes (CC BY-NC-SA) may replace them by hand under the same names.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JELLYFIN_DIR = ROOT / "jellyfin"
SOURCES_DIR = JELLYFIN_DIR / "sources"
SCRATCH = JELLYFIN_DIR / "scratch"

DOWNLOAD_TIMEOUT = 60
CHUNK = 1 << 20


class MissingFfmpeg(RuntimeError):
    pass


def ffmpeg(*args: str, timeout: int = 1800) -> None:
    exe = shutil.which("ffmpeg")
    if exe is None:
        raise MissingFfmpeg("host ffmpeg missing")
    subprocess.run(
        [exe, "-v", "error", "-y", *args],
        check=True,
        stdin=subprocess.DEVNULL,
        timeout=timeout,
    )


def has_encoder(name: str) -> bool:
    exe = shutil.which("ffmpeg")
    if exe is None:
        raise MissingFfmpeg("host ffmpeg missing")
    out = subprocess.run(
        [exe, "-hide_banner", "-encoders"],
        check=True,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=60,
    ).stdout
    return any(line.split()[1:2] == [name] for line in out.splitlines())


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    file: str
    unzip_member: str | None
    sha256: str | None


# The sha256 is of the final file (the extracted member for a zip). Pinned after the first
# verified download (trust on first use); every later run checks it.
SOURCES: dict[str, Source] = {
    "bbb": Source(
        name="bbb",
        url="https://download.blender.org/demo/movies/BBB/bbb_sunflower_1080p_30fps_normal.mp4.zip",
        file="bbb_sunflower_1080p_30fps_normal.mp4",
        unzip_member="bbb_sunflower_1080p_30fps_normal.mp4",
        sha256="ae51005850b0ff757fe60c3dd7a12d754d3cd2397d87d939b55235e457f97658",
    ),
    "sintel": Source(
        name="sintel",
        url="https://download.blender.org/durian/movies/Sintel.2010.1080p.mkv",
        file="Sintel.2010.1080p.mkv",
        unzip_member=None,
        sha256="97f1dbc66231df42ad49bd8c29aa174b8f48933058e47e7157d4ba63d93a8efa",
    ),
    "tos": Source(
        name="tos",
        url="https://download.blender.org/demo/movies/ToS/tears_of_steel_720p.mov",
        file="tears_of_steel_720p.mov",
        unzip_member=None,
        sha256="efa9062d9cdb7a338e40ad530dfdf234806743f29ae6a1a136b97ece4e588e8f",
    ),
}

MOVIES: dict[str, tuple[str, str]] = {
    "bbb": ("Big Buck Bunny (2008)", ".mp4"),
    "sintel": ("Sintel (2010)", ".mkv"),
    "tos": ("Tears of Steel (2012)", ".mkv"),
}


NAMES = [*MOVIES, "pioneer"]


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, target: Path) -> None:
    with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT) as resp, target.open("wb") as out:
        shutil.copyfileobj(resp, out, CHUNK)


def fetch_source(name: str) -> Path:
    """Download one source (or keep the verified file already there) and return its path."""
    source = SOURCES[name]
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    SOURCES_DIR.chmod(0o755)
    dest = SOURCES_DIR / source.file
    if dest.exists():
        digest = sha256_of(dest)
        if source.sha256 is None or digest == source.sha256:
            if source.sha256 is None:
                print(f"sha256 {name} {digest}")
            return dest
        dest.unlink()  # stale or damaged: fetch it again
    part = SOURCES_DIR / (source.file + ".part")
    if source.unzip_member is None:
        _download(source.url, part)
    else:
        archive = SOURCES_DIR / (source.file + ".zip.part")
        try:
            _download(source.url, archive)
            with (
                zipfile.ZipFile(archive) as bundle,
                bundle.open(source.unzip_member) as member,
                part.open("wb") as out,
            ):
                shutil.copyfileobj(member, out, CHUNK)
        finally:
            archive.unlink(missing_ok=True)
    digest = sha256_of(part)
    if source.sha256 is None:
        print(f"sha256 {name} {digest}")
    elif digest != source.sha256:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"sha256 mismatch for {name}: download refused")
    part.chmod(0o644)
    part.rename(dest)
    return dest


def movie_path(name: str) -> Path:
    title, ext = MOVIES[name]
    return SCRATCH / "Movies" / title / f"{title}{ext}"


def _prepare_folder(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    folder.chmod(0o755)


def build_movie(name: str) -> Path:
    """Lay one film out as Movies/Title (Year)/Title (Year).ext; return the final path."""
    source = SOURCES_DIR / SOURCES[name].file
    if not source.exists():
        raise FileNotFoundError(f"source for {name} missing: run the sources subcommand first")
    dest = movie_path(name)
    _prepare_folder(dest.parent.parent)
    _prepare_folder(dest.parent)
    if dest.exists() and (name == "tos" or os.path.samefile(source, dest)):
        return dest
    part = dest.with_name(dest.name + ".part")
    part.unlink(missing_ok=True)
    if name == "tos":
        ffmpeg("-i", str(source), "-map", "0", "-c", "copy", "-f", "matroska", str(part))
        part.chmod(0o644)
        part.replace(dest)
        return dest
    dest.unlink(missing_ok=True)
    try:
        os.link(source, dest)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        shutil.copyfile(source, part)
        part.chmod(0o644)
        part.replace(dest)
    else:
        dest.chmod(0o644)
    return dest


SERIES = "Pioneer One"
EPISODE_OFFSETS = {1: 120, 2: 300, 3: 480}
EPISODE_SECONDS = 60


def episode_path(n: int) -> Path:
    return SCRATCH / "TV" / SERIES / "Season 01" / f"{SERIES} S01E{n:02d}.mkv"


def episode_command(n: int, source: Path, out: Path) -> list[str]:
    """The ffmpeg arguments that cut episode n from the Sintel source."""
    if n not in EPISODE_OFFSETS:
        raise ValueError(f"no episode {n}: use 1 to {len(EPISODE_OFFSETS)}")
    return [
        "-ss",
        str(EPISODE_OFFSETS[n]),
        "-i",
        str(source),
        "-t",
        str(EPISODE_SECONDS),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0",
        "-vf",
        "scale=1280:720",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-ac",
        "2",
        "-metadata:s:a:0",
        "language=eng",
        "-f",
        "matroska",
        str(out),
    ]


def build_episode(n: int) -> Path:
    """Cut one stand-in episode; an existing episode is kept."""
    source = SOURCES_DIR / SOURCES["sintel"].file
    if not source.exists():
        raise FileNotFoundError("source for sintel missing: run the sources subcommand first")
    dest = episode_path(n)
    _prepare_folder(dest.parent.parent)
    _prepare_folder(dest.parent)
    if dest.exists():
        return dest
    if not has_encoder("libx264"):
        raise RuntimeError("the host ffmpeg has no libx264 encoder")
    part = dest.with_name(dest.name + ".part")
    part.unlink(missing_ok=True)
    ffmpeg(*episode_command(n, source, part))
    part.chmod(0o644)
    part.replace(dest)
    return dest


def _size_mb(path: Path) -> str:
    return f"{path.stat().st_size / 1_000_000:.1f} MB"


def cmd_sources(names: list[str]) -> int:
    wanted = ["sintel" if name == "pioneer" else name for name in names]
    for name in dict.fromkeys(wanted):
        path = fetch_source(name)
        print(f"source {name} {path.name} {_size_mb(path)}")
    return 0


def cmd_library(names: list[str]) -> int:
    for name in names:
        if name == "pioneer":
            for number in EPISODE_OFFSETS:
                path = build_episode(number)
                print(f"library pioneer {path.name} {_size_mb(path)}")
        else:
            path = build_movie(name)
            print(f"library {name} {path.name} {_size_mb(path)}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Build the Jellyfin scratch library")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("sources", "library"):
        one = sub.add_parser(command)
        one.add_argument("--only", nargs="+", choices=NAMES, metavar="NAME")
    args = parser.parse_args(argv[1:])
    names = args.only or NAMES
    try:
        if args.command == "sources":
            return cmd_sources(names)
        return cmd_library(names)
    except MissingFfmpeg as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except (RuntimeError, FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"FAIL {args.command}: {exc}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, OSError) as exc:
        print(f"FAIL {args.command}: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
