# TV compatibility

Hisense TV on VIDAA OS (model line: recorded at the TV session), firmware V0003.09.60A.Q0707, test date: not tested yet, Jellyfin 12.3.0 (image tag 12.3.20261023-013714), the TV's built-in browser (version recorded at the TV session), wired Ethernet.

The matrix measures the stock Jellyfin web client on this browser, not a custom player. MKV rows remux by construction, because the stock client never direct-plays MKV on VIDAA, so the matrix is a floor for what Phase 5's own device profile can do. The Method column comes from the server: the ffmpeg log type of the clip (Remux, DirectStream or Transcode) cross-checked with Jellyfin's `TranscodingInfo`, with `Direct play` only when no ffmpeg job ran; the Reason column copies Jellyfin's `TranscodeReasons` verbatim. The 1080p video-and-audio group and the Subtitles group decide the verdict; the PGS, 4K/HDR10 and real-release rows are information only (D-85, D-86, D-99). Phase 5 builds its device profile from this document. It never records a serial number, device ID, Netflix ESN, MAC address, LAN address or account name. Refresh the matrix with `python3 scripts/tv_gate.py render --doc docs/tv-compatibility.md` and check the document with `python3 scripts/tv_gate.py validate`.

<!-- tv-gate:matrix:begin -->

## 1080p video and audio

| ID | Container | Video | Audio | Subtitles | Resolution | Method | Reason | Picture and sound OK |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A01 | MKV | H.264 | AAC | none | 1080p | not tested | - | not tested |
| A02 | MKV | H.264 | AC3 | none | 1080p | not tested | - | not tested |
| A03 | MKV | H.264 | EAC3 | none | 1080p | not tested | - | not tested |
| A04 | MKV | H.264 | DTS | none | 1080p | not tested | - | not tested |
| A05 | MKV | HEVC 8-bit | AAC | none | 1080p | not tested | - | not tested |
| A06 | MKV | HEVC 8-bit | AC3 | none | 1080p | not tested | - | not tested |
| A07 | MKV | HEVC 8-bit | EAC3 | none | 1080p | not tested | - | not tested |
| A08 | MKV | HEVC 8-bit | DTS | none | 1080p | not tested | - | not tested |
| A09 | MKV | HEVC 10-bit | AAC | none | 1080p | not tested | - | not tested |
| A10 | MKV | HEVC 10-bit | AC3 | none | 1080p | not tested | - | not tested |
| A11 | MKV | HEVC 10-bit | EAC3 | none | 1080p | not tested | - | not tested |
| A12 | MKV | HEVC 10-bit | DTS | none | 1080p | not tested | - | not tested |
| A13 | MP4 | H.264 | AAC | none | 1080p | not tested | - | not tested |
| A14 | MP4 | H.264 | AC3 | none | 1080p | not tested | - | not tested |
| A15 | MP4 | H.264 | EAC3 | none | 1080p | not tested | - | not tested |
| A16 | MP4 | H.264 | DTS | none | 1080p | not tested | - | not tested |
| A17 | MP4 | HEVC 8-bit | AAC | none | 1080p | not tested | - | not tested |
| A18 | MP4 | HEVC 8-bit | AC3 | none | 1080p | not tested | - | not tested |
| A19 | MP4 | HEVC 8-bit | EAC3 | none | 1080p | not tested | - | not tested |
| A20 | MP4 | HEVC 8-bit | DTS | none | 1080p | not tested | - | not tested |
| A21 | MP4 | HEVC 10-bit | AAC | none | 1080p | not tested | - | not tested |
| A22 | MP4 | HEVC 10-bit | AC3 | none | 1080p | not tested | - | not tested |
| A23 | MP4 | HEVC 10-bit | EAC3 | none | 1080p | not tested | - | not tested |
| A24 | MP4 | HEVC 10-bit | DTS | none | 1080p | not tested | - | not tested |

## Subtitles

| ID | Container | Video | Audio | Subtitles | Resolution | Method | Reason | Picture and sound OK |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S01 | MKV | H.264 | AAC | SRT (external file) | 1080p | not tested | - | not tested |
| S02 | MKV | H.264 | AAC | SRT (embedded) | 1080p | not tested | - | not tested |
| S03 | MKV | H.264 | AAC | ASS (embedded) | 1080p | not tested | - | not tested |
| S04 | MP4 | H.264 | AAC | MP4 text (embedded) | 1080p | not tested | - | not tested |

## Image subtitles (PGS) — information only

| ID | Container | Video | Audio | Subtitles | Resolution | Method | Reason | Picture and sound OK |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P01 | MKV | H.264 | AAC | PGS (embedded) | 1080p | not tested | no PGS encoder in ffmpeg (D-99) | not tested |

burn-in forced: not tested

## 4K and HDR10 — information only

| ID | Container | Video | Audio | Subtitles | Resolution | Method | Reason | Picture and sound OK |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| K01 | MP4 | HEVC 10-bit HDR10 | none | none | 2160p | not tested | - | not tested |
| K02 | MP4 | HEVC 10-bit | none | none | 2160p | not tested | - | not tested |
| K03 | MP4 | H.264 | none | none | 2160p | not tested | - | not tested |

## Real-release samples (sanity check)

| ID | Container | Video | Audio | Subtitles | Resolution | Method | Reason | Picture and sound OK |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R01 | MKV | H.264 | AC3 | SRT (embedded) | 1080p | not tested | Sintel as downloaded: AC3 5.1 and ten embedded SRT tracks | not tested |
| R02 | MP4 | H.264 | MP3 | none | 1080p | not tested | Big Buck Bunny as downloaded: MP3 stereo first, AC3 5.1 second | not tested |
| R03 | MP4 | HEVC 10-bit | none | none | 1080p | not tested | - | not tested |

<!-- tv-gate:matrix:end -->

## Address check

- `.local` name resolved on the TV: not tested
- Tested name: `<laptop-name>.local`
- Date: not tested
- Household default address: `http://<laptop-ip>/jellyfin` (stays the default until a `.local` name passes on the TV, D-81)

## Streaming bitrate

- Measured LAN throughput: not tested
- Source of the measurement: not tested
- Limit (JELLYFIN_MAX_BITRATE_MBPS): 60 Mbps, the default until measured (D-96)

## Verdict

**Pending**: the real-TV session has not run yet.
