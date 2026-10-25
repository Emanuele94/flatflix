#!/usr/bin/env python3
"""Build the Jellyfin scratch library from CC-licensed Blender open movies (standard library only).

Usage:
    python3 scripts/make_compat_clips.py sources [--only NAME ...]
    python3 scripts/make_compat_clips.py library [--only NAME ...]
    python3 scripts/make_compat_clips.py clips [--only ID ...] [--verify]

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

`clips` (D-84, D-85, D-98, D-99) builds the codec matrix for the TV gate in jellyfin/scratch/Compat
(the admin-only Compat library): CATALOGUE lists every row by id, and each clip file name starts
with its row id and a space, so the item Jellyfin plays names its row. The A rows (MKV and MP4 x
H.264, HEVC 8-bit and 10-bit x AAC, AC3, EAC3 and DTS, 1080p, 60 s) are muxed by stream copy from
one video and one audio intermediate each (BBB video and Sintel audio, both from second 60), kept
under jellyfin/sources/intermediate. Every file is written under a `.part` name and renamed only
when complete. `clips --verify` proves every file's container and codecs with ffprobe. The
manifest jellyfin/tv-gate/clips.json records, per row id, the file, an `n/a - <reason>` when a muxer
refuses the combination, a note and the probed codecs. Nothing generated or downloaded is
committed (the jellyfin folder is gitignored).
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
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


def ffmpeg(*args: str, timeout: int = 1800, capture_stderr: bool = False) -> None:
    """Run host ffmpeg by argument list. With capture_stderr a failure carries ffmpeg's stderr."""
    exe = shutil.which("ffmpeg")
    if exe is None:
        raise MissingFfmpeg("host ffmpeg missing")
    subprocess.run(
        [exe, "-v", "error", "-y", *args],
        check=True,
        stdin=subprocess.DEVNULL,
        stderr=subprocess.PIPE if capture_stderr else None,
        text=True,
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


# --- the codec matrix (D-84, D-85, D-98, D-99) ------------------------------------------

INTERMEDIATE_DIR = SOURCES_DIR / "intermediate"
MANIFEST = JELLYFIN_DIR / "tv-gate" / "clips.json"
CLIP_OFFSET = 60  # seconds into the source where the one-minute cut starts
CLIP_SECONDS = 60


@dataclass(frozen=True)
class Row:
    id: str
    group: str
    container: str
    video: str
    audio: str
    subtitles: str
    resolution: str
    gating: bool
    origin: str  # generated, download or original
    note: str = ""


# (key, heading, gating): the group headings use the words of the UI-SPEC compatibility doc.
GROUPS: tuple[tuple[str, str, bool], ...] = (
    ("av", "1080p video and audio", True),
    ("subs", "Subtitles", True),
    ("pgs", "Image subtitles (PGS) — information only", False),
    ("uhd", "4K and HDR10 — information only", False),
    ("real", "Real-release samples (sanity check)", False),
)

PGS_NOTE = "no PGS encoder in ffmpeg (D-99)"


def _build_catalogue() -> tuple[Row, ...]:
    rows: list[Row] = []
    number = 0
    for container in ("MKV", "MP4"):
        for video in ("H.264", "HEVC 8-bit", "HEVC 10-bit"):
            for audio in ("AAC", "AC3", "EAC3", "DTS"):
                number += 1
                rows.append(
                    Row(f"A{number:02d}", "av", container, video, audio, "none", "1080p", True, "generated")
                )
    rows += [
        Row("S01", "subs", "MKV", "H.264", "AAC", "SRT (external file)", "1080p", True, "generated"),
        Row("S02", "subs", "MKV", "H.264", "AAC", "SRT (embedded)", "1080p", True, "generated"),
        Row("S03", "subs", "MKV", "H.264", "AAC", "ASS (embedded)", "1080p", True, "generated"),
        Row("S04", "subs", "MP4", "H.264", "AAC", "MP4 text (embedded)", "1080p", True, "generated"),
        Row("P01", "pgs", "MKV", "H.264", "AAC", "PGS (embedded)", "1080p", False, "generated", PGS_NOTE),
        Row("K01", "uhd", "MP4", "HEVC 10-bit HDR10", "none", "none", "2160p", False, "download"),
        Row("K02", "uhd", "MP4", "HEVC 10-bit", "none", "none", "2160p", False, "download"),
        Row("K03", "uhd", "MP4", "H.264", "none", "none", "2160p", False, "download"),
        Row(
            "R01", "real", "MKV", "H.264", "AC3", "SRT (embedded)", "1080p", False, "original",
            "Sintel as downloaded: AC3 5.1 and ten embedded SRT tracks",
        ),
        Row(
            "R02", "real", "MP4", "H.264", "MP3", "none", "1080p", False, "original",
            "Big Buck Bunny as downloaded: MP3 stereo first, AC3 5.1 second",
        ),
        Row("R03", "real", "MP4", "HEVC 10-bit", "none", "none", "1080p", False, "download"),
    ]
    return tuple(rows)


CATALOGUE: tuple[Row, ...] = _build_catalogue()
ROW_IDS = tuple(r.id for r in CATALOGUE)

_VIDEO_TAGS = {
    "H.264": "H264",
    "HEVC 8-bit": "HEVC8",
    "HEVC 10-bit": "HEVC10",
    "HEVC 10-bit HDR10": "HDR10",
}
_AUDIO_TAGS = {"AAC": "AAC", "AC3": "AC3", "EAC3": "EAC3", "DTS": "DTS", "MP3": "MP3", "none": None}
_SUBTITLE_TAGS = {
    "none": None,
    "SRT (external file)": "SRTEXT",
    "SRT (embedded)": "SRT",
    "ASS (embedded)": "ASS",
    "MP4 text (embedded)": "MOVTEXT",
    "PGS (embedded)": "PGS",
}
_EXTENSIONS = {"MKV": ".mkv", "MP4": ".mp4"}
_FORMATS = {"MKV": "matroska", "MP4": "mp4"}  # ffmpeg muxer and ffprobe family name
_VIDEO_CODECS = {
    "H.264": "h264",
    "HEVC 8-bit": "hevc",
    "HEVC 10-bit": "hevc",
    "HEVC 10-bit HDR10": "hevc",
}
_AUDIO_CODECS = {"AAC": "aac", "AC3": "ac3", "EAC3": "eac3", "DTS": "dts", "MP3": "mp3", "none": None}
_SUBTITLE_CODECS = {
    "none": None,
    "SRT (external file)": None,
    "SRT (embedded)": "subrip",
    "ASS (embedded)": "ass",
    "MP4 text (embedded)": "mov_text",
    "PGS (embedded)": "hdmv_pgs_subtitle",
}
_WIDTHS = {"1080p": 1920, "2160p": 3840}


def clip_path(row: Row) -> Path:
    """Compat/<id> <container> <video tag> <audio tag>[ <subtitle tag>].<ext>: the id comes first."""
    parts = [row.id, row.container, _VIDEO_TAGS[row.video]]
    parts += [tag for tag in (_AUDIO_TAGS[row.audio], _SUBTITLE_TAGS[row.subtitles]) if tag]
    return SCRATCH / "Compat" / (" ".join(parts) + _EXTENSIONS[row.container])


def mux_args(row: Row, video: Path, audio: Path, out: Path) -> list[str]:
    """The ffmpeg arguments that copy one video and one audio intermediate into the row's file."""
    args = [
        "-i", str(video),
        "-i", str(audio),
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c", "copy",
        "-metadata:s:a:0", "language=eng",
    ]  # fmt: skip
    if row.container == "MP4":
        if "HEVC" in row.video:
            args += ["-tag:v", "hvc1"]
        args += ["-movflags", "+faststart"]
    args += ["-f", _FORMATS[row.container], str(out)]
    return args


def expected_streams(row: Row) -> dict:
    """What ffprobe must report for the row's file (ffprobe's names)."""
    want: dict = {
        "container": _FORMATS[row.container],
        "video": _VIDEO_CODECS[row.video],
        "pix_fmt": "yuv420p10le" if "10-bit" in row.video else "yuv420p",
        "audio": _AUDIO_CODECS[row.audio],
        "subtitles": _SUBTITLE_CODECS[row.subtitles],
    }
    if "HDR10" in row.video:
        want["color_transfer"] = "smpte2084"
    return want


def probe(path: Path) -> dict:
    exe = shutil.which("ffprobe")
    if exe is None:
        raise MissingFfmpeg("host ffprobe missing")
    out = subprocess.run(
        [exe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=120,
    ).stdout
    return json.loads(out)


def _first_stream(probe_json: dict, kind: str) -> dict:
    return next((s for s in probe_json.get("streams") or [] if s.get("codec_type") == kind), {})


def probed(probe_json: dict) -> dict:
    """The manifest's view of a probe: container family and the first codec of each kind."""
    names = str((probe_json.get("format") or {}).get("format_name") or "").split(",")
    container = "matroska" if "matroska" in names else "mp4" if "mp4" in names else names[0] or None
    return {
        "container": container,
        "video": _first_stream(probe_json, "video").get("codec_name"),
        "audio": _first_stream(probe_json, "audio").get("codec_name"),
        "subtitles": _first_stream(probe_json, "subtitle").get("codec_name"),
    }


def probe_mismatches(row: Row, probe_json: dict) -> list[str]:
    """One message per field in which the probe differs from what the row promises."""
    want = expected_streams(row)
    got = probed(probe_json)
    video = _first_stream(probe_json, "video")
    problems: list[str] = []

    def check(field: str, expected: object, actual: object) -> None:
        if expected != actual:
            problems.append(f"{field}: expected {expected or 'none'}, got {actual or 'none'}")

    check("container", want["container"], got["container"])
    check("video", want["video"], got["video"])
    check("pix_fmt", want["pix_fmt"], video.get("pix_fmt"))
    check("audio", want["audio"], got["audio"])
    # A downloaded or original file may carry more subtitle tracks than its cell names.
    if want["subtitles"] is not None or row.origin == "generated":
        check("subtitles", want["subtitles"], got["subtitles"])
    if "color_transfer" in want:
        check("color_transfer", want["color_transfer"], video.get("color_transfer"))
    if "width" in video:
        check("width", _WIDTHS[row.resolution], video["width"])
    return problems


# --- the manifest ---------------------------------------------------------------------


def read_manifest() -> dict:
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def write_manifest(entries: dict) -> None:
    """Write beside the old file and replace it, so a failed write leaves the old one intact."""
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp = tempfile.mkstemp(dir=MANIFEST.parent, prefix=".clips-", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(entries, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.chmod(temp, 0o644)
        os.replace(temp, MANIFEST)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def update_manifest(new: dict) -> dict:
    """Merge entries into the manifest (rows not named keep theirs), in catalogue order."""
    merged = {**read_manifest(), **new}
    ordered = {rid: merged[rid] for rid in ROW_IDS if rid in merged}
    write_manifest(ordered)
    return ordered


def _entry(file: Path | None, na: str | None, note: str | None, probed_values: dict | None) -> dict:
    return {
        "file": file.name if file else None,
        "na": na,
        "note": note or None,
        "probed": probed_values,
    }


# --- generating the clips ---------------------------------------------------------------

# One intermediate per video and per audio codec, encoded once and muxed by stream copy.
VIDEO_ENCODES: dict[str, tuple[str, list[str]]] = {
    "H.264": (
        "video-h264.mkv",
        [
            "-c:v", "libx264", "-preset", "veryfast", "-profile:v", "high", "-level:v", "4.1",
            "-pix_fmt", "yuv420p", "-b:v", "8M", "-maxrate", "10M", "-bufsize", "20M",
        ],
    ),
}  # fmt: skip
AUDIO_ENCODES: dict[str, tuple[str, list[str]]] = {
    "AAC": ("audio-aac.mka", ["-c:a", "aac", "-ac", "2", "-b:a", "192k"]),
}


def _folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o755)


def _finish(part: Path, dest: Path) -> None:
    part.chmod(0o644)
    part.replace(dest)


def _encoder_of(args: list[str]) -> str:
    for flag in ("-c:v", "-c:a"):
        if flag in args:
            return args[args.index(flag) + 1]
    raise ValueError("no encoder in the arguments")


def _intermediate(name: str, source: str, selection: list[str], encode: list[str]) -> Path:
    """Encode one minute of a source once; an existing intermediate is kept."""
    dest = INTERMEDIATE_DIR / name
    if dest.exists():
        return dest
    encoder = _encoder_of(encode)
    if not has_encoder(encoder):
        raise RuntimeError(f"the host ffmpeg has no {encoder} encoder")
    path = fetch_source(source)
    _folder(INTERMEDIATE_DIR)
    part = dest.with_name(dest.name + ".part")
    part.unlink(missing_ok=True)
    ffmpeg(
        "-ss", str(CLIP_OFFSET), "-t", str(CLIP_SECONDS), "-i", str(path),
        *selection, *encode, "-f", "matroska", str(part),
    )  # fmt: skip
    _finish(part, dest)
    return dest


def video_intermediate(video: str) -> Path:
    if video not in VIDEO_ENCODES:
        raise RuntimeError(f"no video encode defined for {video}")
    name, encode = VIDEO_ENCODES[video]
    return _intermediate(name, "bbb", ["-map", "0:v:0", "-an", "-sn"], encode)


def audio_intermediate(audio: str) -> Path:
    if audio not in AUDIO_ENCODES:
        raise RuntimeError(f"no audio encode defined for {audio}")
    name, encode = AUDIO_ENCODES[audio]
    return _intermediate(
        name, "sintel", ["-map", "0:a:0", "-vn", "-sn"], [*encode, "-metadata:s:a:0", "language=eng"]
    )


def _channel_words(count: int | None) -> str:
    return {1: "mono", 2: "stereo", 6: "5.1"}.get(count or 0, f"{count} channels")


def build_av(row: Row) -> dict:
    """Mux one A row from its two intermediates; an existing file is kept; returns its entry."""
    video, audio = video_intermediate(row.video), audio_intermediate(row.audio)
    dest = clip_path(row)
    _folder(dest.parent)
    if not dest.exists():
        part = dest.with_name(dest.name + ".part")
        part.unlink(missing_ok=True)
        try:
            ffmpeg(*mux_args(row, video, audio, part), capture_stderr=True)
        except subprocess.CalledProcessError:
            part.unlink(missing_ok=True)
            raise
        _finish(part, dest)
    found = probe(dest)
    channels = _first_stream(probe(audio), "audio").get("channels")
    return _entry(dest, None, f"audio {_channel_words(channels)}", probed(found))


def build_row(row: Row) -> dict:
    if row.group == "av":
        return build_av(row)
    raise RuntimeError(f"{row.id}: this version does not build the {row.group} group")


def _size_mb(path: Path) -> str:
    return f"{path.stat().st_size / 1_000_000:.1f} MB"


def cmd_clips(ids: list[str], verify: bool) -> int:
    if verify:
        return verify_clips(ids)
    for rid in ids:
        row = next(r for r in CATALOGUE if r.id == rid)
        entry = build_row(row)
        update_manifest({rid: entry})
        if entry["file"]:
            print(f"clip {rid} {entry['file']} {_size_mb(clip_path(row))}")
        else:
            print(f"clip {rid} no file ({entry['na'] or entry['note']})")
    return 0


def verify_clips(ids: list[str]) -> int:
    manifest = read_manifest()
    failures = 0
    for rid in ids:
        row = next(r for r in CATALOGUE if r.id == rid)
        entry = manifest.get(rid)
        if entry is None:
            failures += 1
            print(f"FAIL {rid}: not built yet")
            continue
        if not entry.get("file"):
            print(f"OK {rid} (no file: {entry.get('na') or entry.get('note')})")
            continue
        path = clip_path(row)
        if not path.is_file():
            failures += 1
            print(f"FAIL {rid}: {path.name} is missing")
            continue
        problems = probe_mismatches(row, probe(path))
        if problems:
            failures += 1
            print(f"FAIL {rid}: " + "; ".join(problems))
        else:
            print(f"OK {rid}")
    return 1 if failures else 0


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
    clips = sub.add_parser("clips")
    clips.add_argument("--only", nargs="+", choices=ROW_IDS, metavar="ID")
    clips.add_argument("--verify", action="store_true", help="prove every file with ffprobe")
    args = parser.parse_args(argv[1:])
    try:
        if args.command == "clips":
            ids = args.only or (
                [rid for rid in ROW_IDS if rid in read_manifest()] if args.verify else list(ROW_IDS)
            )
            return cmd_clips(ids, args.verify)
        names = args.only or NAMES
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
