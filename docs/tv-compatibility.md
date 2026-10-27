# TV compatibility

Hisense 50A6Q TV on VIDAA OS, firmware V0003.09.60A.Q0707, test date: 2026-10-26, Jellyfin 12.3.0 (image tag 12.3.20261023-013714) with the Jellyfin web client 12.3.0, the TV's built-in VIDAA browser (version not shown), wired Ethernet.

The matrix measures the stock Jellyfin web client on this browser, not a custom player. MKV rows remux by construction, because the stock client never direct-plays MKV on VIDAA, so the matrix is a floor for what Phase 5's own device profile can do. The Method column comes from the server: the ffmpeg log type of the clip (Remux, DirectStream or Transcode) cross-checked with Jellyfin's `TranscodingInfo`, with `Direct play` only when no ffmpeg job ran; the Reason column copies Jellyfin's `TranscodeReasons` verbatim. The 1080p video-and-audio group and the Subtitles group decide the verdict; the PGS, 4K/HDR10 and real-release rows are information only (D-85, D-86, D-99). Phase 5 builds its device profile from this document. It never records a serial number, device ID, Netflix ESN, MAC address, LAN address or account name. Refresh the matrix with `python3 scripts/tv_gate.py render --doc docs/tv-compatibility.md` and check the document with `python3 scripts/tv_gate.py validate`.

<!-- tv-gate:matrix:begin -->

## 1080p video and audio

| ID | Container | Video | Audio | Subtitles | Resolution | Method | Reason | Picture and sound OK |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A01 | MKV | H.264 | AAC | none | 1080p | Remux | ContainerNotSupported | yes |
| A02 | MKV | H.264 | AC3 | none | 1080p | Audio transcode | ContainerNotSupported, AudioCodecNotSupported | yes |
| A03 | MKV | H.264 | EAC3 | none | 1080p | Audio transcode | ContainerNotSupported, AudioCodecNotSupported | yes |
| A04 | MKV | H.264 | DTS | none | 1080p | Audio transcode | ContainerNotSupported, AudioCodecNotSupported | yes |
| A05 | MKV | HEVC 8-bit | AAC | none | 1080p | Remux | ContainerNotSupported | yes |
| A06 | MKV | HEVC 8-bit | AC3 | none | 1080p | Audio transcode | ContainerNotSupported, AudioCodecNotSupported | yes |
| A07 | MKV | HEVC 8-bit | EAC3 | none | 1080p | Audio transcode | ContainerNotSupported, AudioCodecNotSupported | yes |
| A08 | MKV | HEVC 8-bit | DTS | none | 1080p | Audio transcode | ContainerNotSupported, AudioCodecNotSupported | yes |
| A09 | MKV | HEVC 10-bit | AAC | none | 1080p | Remux | ContainerNotSupported | yes |
| A10 | MKV | HEVC 10-bit | AC3 | none | 1080p | Audio transcode | ContainerNotSupported, AudioCodecNotSupported | yes |
| A11 | MKV | HEVC 10-bit | EAC3 | none | 1080p | Audio transcode | ContainerNotSupported, AudioCodecNotSupported | yes |
| A12 | MKV | HEVC 10-bit | DTS | none | 1080p | Audio transcode | ContainerNotSupported, AudioCodecNotSupported | yes |
| A13 | MP4 | H.264 | AAC | none | 1080p | Direct play | - | yes |
| A14 | MP4 | H.264 | AC3 | none | 1080p | Direct play | - | yes |
| A15 | MP4 | H.264 | EAC3 | none | 1080p | Direct play | - | yes |
| A16 | MP4 | H.264 | DTS | none | 1080p | Audio transcode | AudioCodecNotSupported | yes |
| A17 | MP4 | HEVC 8-bit | AAC | none | 1080p | Direct play | - | yes |
| A18 | MP4 | HEVC 8-bit | AC3 | none | 1080p | Direct play | - | yes |
| A19 | MP4 | HEVC 8-bit | EAC3 | none | 1080p | Direct play | - | yes |
| A20 | MP4 | HEVC 8-bit | DTS | none | 1080p | Audio transcode | AudioCodecNotSupported | yes |
| A21 | MP4 | HEVC 10-bit | AAC | none | 1080p | Direct play | - | yes |
| A22 | MP4 | HEVC 10-bit | AC3 | none | 1080p | Direct play | - | yes |
| A23 | MP4 | HEVC 10-bit | EAC3 | none | 1080p | Direct play | - | yes |
| A24 | MP4 | HEVC 10-bit | DTS | none | 1080p | Audio transcode | AudioCodecNotSupported | yes |

## Subtitles

| ID | Container | Video | Audio | Subtitles | Resolution | Method | Reason | Picture and sound OK |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S01 | MKV | H.264 | AAC | SRT (external file) | 1080p | Remux | ContainerNotSupported, AudioCodecNotSupported | yes |
| S02 | MKV | H.264 | AAC | SRT (embedded) | 1080p | Remux | ContainerNotSupported | yes |
| S03 | MKV | H.264 | AAC | ASS (embedded) | 1080p | Remux | ContainerNotSupported, AudioCodecNotSupported | yes |
| S04 | MP4 | H.264 | AAC | MP4 text (embedded) | 1080p | Direct play | - | yes |

## Image subtitles (PGS) — information only

| ID | Container | Video | Audio | Subtitles | Resolution | Method | Reason | Picture and sound OK |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P01 | MKV | H.264 | AAC | PGS (embedded) | 1080p | not tested | no PGS encoder in ffmpeg (D-99) | not tested |

burn-in forced: not tested

## 4K and HDR10 — information only

| ID | Container | Video | Audio | Subtitles | Resolution | Method | Reason | Picture and sound OK |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| K01 | MP4 | HEVC 10-bit HDR10 | none | none | 2160p | Direct play | - | yes |
| K02 | MP4 | HEVC 10-bit | none | none | 2160p | Direct play | - | yes |
| K03 | MP4 | H.264 | none | none | 2160p | Direct play | - | yes |

## Real-release samples (sanity check)

| ID | Container | Video | Audio | Subtitles | Resolution | Method | Reason | Picture and sound OK |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R01 | MKV | H.264 | AC3 | SRT (embedded) | 1080p | Audio transcode | ContainerNotSupported, AudioCodecNotSupported — Sintel as downloaded: AC3 5.1 and ten embedded SRT tracks | yes |
| R02 | MP4 | H.264 | MP3 | none | 1080p | Direct play | - — Big Buck Bunny as downloaded: MP3 stereo first, AC3 5.1 second | yes |
| R03 | MP4 | HEVC 10-bit | none | none | 1080p | Direct play | - | yes |

<!-- tv-gate:matrix:end -->

## Address check

- `.local` name resolved on the TV: no (the TV browser shows ERR_NAME_NOT_RESOLVED)
- On a phone: yes
- Tested name: `<laptop-name>.local`
- Date: 2026-10-26
- Household default address: `http://<laptop-ip>/jellyfin` (stays the default until a `.local` name passes on the TV, D-81)
- Same address after laptop and router restart: yes (2026-10-27)

## Streaming bitrate

- Measured LAN throughput: 50 Mbps
- Source of the measurement: speedtest.net in the TV's browser, which measures the internet link, not the TV-to-laptop LAN link, so treat it as a conservative lower bound
- Limit (JELLYFIN_MAX_BITRATE_MBPS): 35 Mbps (floor of 70 % of the measurement, kept within 20-80)
- Dashboard shows the limit in Mbps: yes (the dashboard showed 60 while the env value was 60, so the unit is Mbps)
- TV web client maximum set to the same value: yes

## Verdict

**GO**

Phase 5 builds its device profile from the rows marked Direct play or Remux above.

1080p content needed video transcoding: never

Jellyfin version tested: 12.3.0

The matrix is the stock web client's floor: Phase 5's own device profile starts from it and can only do better.
