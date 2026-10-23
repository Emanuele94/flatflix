#!/usr/bin/env python3
"""Generate the probe fixtures of the opt-in real-sandbox suite with the host ffmpeg.

Usage: python3 scripts/make_probe_fixtures.py <out_dir>

Writes good.mkv, good.mp4 (moov atom last, size not a multiple of 512), good.avi,
mismatch.mkv (an MP4 named .mkv), audio_only.mkv, truncated.mkv, fake.mkv (an
executable renamed), text.mkv and tiny.mkv into <out_dir> (files 0644, folder 0755)
and prints file names and sizes only. Standard library only; ffmpeg runs through
argument lists, never a shell.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

SECONDS = 60
VIDEO_SOURCE = f"testsrc=size=320x240:rate=25:duration={SECONDS}"
AUDIO_SOURCE = f"sine=frequency=440:duration={SECONDS}"


class MissingFfmpeg(RuntimeError):
    pass


def _ffmpeg(*args: str) -> None:
    exe = shutil.which("ffmpeg")
    if exe is None:
        raise MissingFfmpeg("host ffmpeg missing")
    subprocess.run(
        [exe, "-v", "error", "-y", *args],
        check=True,
        stdin=subprocess.DEVNULL,
        timeout=300,
    )


def _has(kind: str, name: str) -> bool:
    exe = shutil.which("ffmpeg")
    if exe is None:
        raise MissingFfmpeg("host ffmpeg missing")
    out = subprocess.run(
        [exe, "-hide_banner", f"-{kind}"],
        check=True,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=60,
    ).stdout
    return any(line.split()[1:2] == [name] for line in out.splitlines())


def _video_codec_args() -> list[str]:
    if _has("encoders", "libx264"):
        return ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    return ["-c:v", "mpeg4"]


def _audio_codec_args(*, mp3_first: bool = False) -> list[str]:
    if mp3_first and _has("encoders", "libmp3lame"):
        return ["-c:a", "libmp3lame"]
    return ["-c:a", "aac"]


def _inputs() -> list[str]:
    return ["-f", "lavfi", "-i", VIDEO_SOURCE, "-f", "lavfi", "-i", AUDIO_SOURCE]


def make_good_mkv(path: Path) -> None:
    _ffmpeg(*_inputs(), *_video_codec_args(), *_audio_codec_args(), "-shortest", str(path))


def make_good_mp4(path: Path) -> None:
    """No faststart, so the moov atom is last; vary the title until the size is off-sector."""
    for attempt in range(40):
        _ffmpeg(
            *_inputs(),
            *_video_codec_args(),
            *_audio_codec_args(),
            "-shortest",
            "-metadata",
            f"title=fixture {attempt}" + "x" * attempt,
            str(path),
        )
        if path.stat().st_size % 512 != 0:
            return
    raise RuntimeError("could not make an MP4 whose size is not a multiple of 512")


def make_good_avi(path: Path) -> None:
    audio = (
        ["-c:a", "libmp3lame"] if _has("encoders", "libmp3lame") else ["-c:a", "pcm_s16le"]
    )
    _ffmpeg(*_inputs(), "-c:v", "mpeg4", *audio, "-shortest", str(path))


def make_audio_only(path: Path) -> None:
    _ffmpeg("-f", "lavfi", "-i", AUDIO_SOURCE, *_audio_codec_args(mp3_first=True), str(path))


def generate(out_dir: Path) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_dir.chmod(0o755)
    make_good_mkv(out_dir / "good.mkv")
    make_good_mp4(out_dir / "good.mp4")
    make_good_avi(out_dir / "good.avi")
    shutil.copyfile(out_dir / "good.mp4", out_dir / "mismatch.mkv")
    make_audio_only(out_dir / "audio_only.mkv")
    good = (out_dir / "good.mkv").read_bytes()
    # Well under 100 kbps over 60 s, yet still a readable Matroska header.
    (out_dir / "truncated.mkv").write_bytes(good[: min(204800, len(good) // 4)])
    # The bytes of a real executable under a video name.
    elf = Path(sys.executable).resolve()
    (out_dir / "fake.mkv").write_bytes(elf.read_bytes())
    (out_dir / "text.mkv").write_text(
        "".join(f"line {n}: this is not a video\n" for n in range(400))[:8192], encoding="utf-8"
    )
    (out_dir / "tiny.mkv").write_bytes(b"x" * 100)
    sizes = {}
    for path in sorted(out_dir.iterdir()):
        path.chmod(0o644)
        sizes[path.name] = path.stat().st_size
    return sizes


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    try:
        sizes = generate(Path(argv[1]))
    except MissingFfmpeg as exc:
        print(str(exc), file=sys.stderr)
        return 3
    for name, size in sizes.items():
        print(f"{name} {size}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
