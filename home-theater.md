# Home Theater App — Project Plan

Oct 16, 2026 · @Ema

## Goal and requirements

A personal home theater app for the household Hisense TV (VIDAA OS), used to browse and watch the films and series in our own library in at least Full HD. It must feel like a real app, launched from an icon on the TV home screen, and be usable by household members who are not technical.

**Requirements**

- Smooth playback at 1080p or better, with no quality loss compared to the original file
- Launch from an icon on the VIDAA home screen, full screen, without going through the browser
- Full use with the remote control alone: arrows, OK, Back, Play/Pause
- Library with posters, plot summaries, seasons and episodes
- "Continue watching" and watched/unwatched state
- Frontend as light as possible, suited to the TV's dated browser

**Out of scope for now**: access from outside the home, multiple users with separate profiles, publishing on the VIDAA store.

## Overall architecture

At home there are only two pieces: the TV, which shows the frontend, and the laptop, where everything else runs in Docker. The only code to write is the frontend.

&#91;embedded content: architecture · TV, laptop and online metadata\]

The TV calls a single address, the Caddy one, which serves the frontend files and forwards API calls and video to Jellyfin. This avoids CORS problems and, when the server moves to another machine, only the IP changes.

## Backend: Jellyfin

The backend is Jellyfin, an open source media server: we do not write server code, we configure it and use it through its REST API. During the trial phase it runs in Docker on the laptop.

**What it gives us out of the box**

- Folder scanning and recognition of films, series, seasons and episodes
- Metadata and images (posters, plot summaries, cast) from sources such as TMDB, stored locally
- Users, watch progress, "continue watching"
- Streaming engine that chooses between direct play, remux and transcoding based on the client profile

**APIs the frontend will use**

| Purpose | What we call |
| --- | --- |
| Authentication | User login or API key created from the admin panel |
| Film and series lists | `Items` endpoint, filtered by type and library |
| Posters | Image endpoints, requesting the already reduced size for the TV |
| Start playback | `PlaybackInfo` with the TV's device profile, returns the streaming URL |
| Progress | Reports for playback start, progress and stop |

**Setup on the laptop**

- `jellyfin/jellyfin` container with volumes for configuration, cache and the media folder, plus a Caddy container in front that serves the frontend and acts as a reverse proxy
- Admin interface on port 8096, from which the library is created
- DHCP reservation on the router, so the laptop always has the same LAN IP

**File naming**, to be followed so that scanning works:

- Films: `Title (Year)/Title (Year).mkv`
- Series: `Series/Season 01/Series S01E01.mkv`

## Frontend: framework choice

Proposed choice: **Preact + Vite**, with a spatial navigation library and a transpiled build for dated browsers. It is very light (Preact weighs about 3 KB), uses the React model I already know, and remains a pure web app that can also be reused for plan B.

**TV constraints**

- CPU and memory far below a phone: no heavy animations, few large images at a time
- Dated VIDAA browser: transpiled build (e.g. the Vite legacy plugin) and real tests on the TV
- Remote control only: spatial navigation is needed (arrows that move focus between nearby elements)

**Options evaluated**

| Option | Weight | Remote control navigation | Pros | Cons |
| --- | --- | --- | --- | --- |
| Preact + Vite | Very low | [preact-spatial-navigation](https://app.unpkg.com/preact-spatial-navigation@1.3.1/files/README.md) library or the [Norigin](https://github.com/noriginmedia/norigin-spatial-navigation) core | React syntax, large ecosystem, normal DOM for the player | Navigation has to be integrated by hand |
| SolidJS | Very low | [solidjs-spatial-navigation](https://github.com/LampaWebDev/solidjs-spatial-navigation), stated as tested on VIDAA | Fine-grained reactivity, excellent performance | Smaller ecosystem, syntax to learn |
| Lightning 3 + Blits | Low, but WebGL rendering | Built-in focus handling | The fastest on cheap TVs, [designed for limited hardware](https://lightningjs.io/blogs/roadToPerformance.html) | Own syntax, WebGL support on VIDAA still to be verified, steep learning curve |
| Vanilla TypeScript | Minimal | To be written from scratch | Zero dependencies | Everything (routing, state, components) has to be rewritten |

**App structure**: four screens (Home, Library, Detail, Player), a thin API client for Jellyfin, a minimal router, and handling of the Back key on every screen.

If tests on the TV show lag when scrolling grids, the fallback is SolidJS; Lightning only if that is not enough either.

## Video playback and codecs

Full HD is achieved by avoiding video transcoding: the TV decodes H.264 and HEVC in hardware, so the server should at most change the container or the audio.

| Case | What Jellyfin does | Server cost | Quality |
| --- | --- | --- | --- |
| File already compatible | Direct play, sends the file as is | None | Original |
| Unsupported container (typically MKV) | Remux into HLS without re-encoding | Very low | Original |
| Unsupported audio (DTS, TrueHD) | Transcodes only the audio | Low | Original video |
| Unsupported video codec | Full transcoding with ffmpeg | High | Reduced |

**Player in the frontend**: native `<video>` element with HLS if the TV supports it, otherwise hls.js on top of Media Source Extensions. The device profile sent to `PlaybackInfo` tells Jellyfin what the TV is capable of.

**Network**: a 1080p stream needs about 8–20 Mbps; Ethernet on the TV where possible, otherwise 5 GHz Wi-Fi.

**Compatibility tests (to do before the frontend)**

- [ ] Open the Jellyfin web interface from the TV and try a few films
- [ ] Check H.264 and HEVC video, including 10-bit
- [ ] Check AAC, AC3, EAC3, DTS audio
- [ ] Check SRT and embedded subtitles
- [ ] Check in the admin panel which playbacks end up being transcoded

## Distribution on the TV

The app reaches the TV as a hosted app: on the TV there is only an icon that opens the URL of our frontend in full screen. The code lives on the server, so every update is visible immediately without reinstalling.

**Plan A: VIDAA icon via a community tool**

- Open source tool that, with a temporary DNS redirect, adds to the VIDAA home screen an app pointing to a URL of our choice
- One-time installation, pointing to `http://<laptop-ip>:<port>`
- Unofficial: a firmware update can break it, and the tool's code must be read before using it
- Official publication (developer account, NDA, certification) makes no sense for home use

**Plan B: Google TV or Fire TV HDMI stick (€30–70)**

- The same frontend packaged in a WebView (e.g. Capacitor) and installed as an APK
- Official, stable installation, codec compatibility usually better
- With HDMI-CEC a single remote control is still enough

The frontend stays a pure web app, with no VIDAA-specific APIs, so moving from plan A to plan B requires no rewrites.

## Risks and mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| The community tool stops working after a VIDAA update | The icon disappears or does not open | Disable automatic updates if possible; plan B with an HDMI stick |
| The laptop is off or changes IP | The app does not open | DHCP reservation; a well-designed "server unreachable" screen; later an always-on server |
| Codecs or subtitles not supported by the TV's player | Heavy transcoding or video that does not start | Compatibility tests before writing the frontend; remux and audio-only transcoding |
| VIDAA browser too dated for modern JS | Blank page or errors | Transpiled build, tests on the TV from the first screen |
| Poor performance in poster grids | Choppy navigation | Images reduced server-side, virtualized lists, fallback to SolidJS |
| Unstable Wi-Fi | Buffering | Ethernet on the TV, maximum bitrate configured in Jellyfin |

## Phases and milestones

The project proceeds in five phases, and the frontend is written only after verifying that the TV plays the files without video transcoding.

&#91;embedded content: project phases · 5 phases, 4 gates\]

Phases 1 and 2 require no code: they exist to remove technical doubts before investing time in the interface.

## Open decisions

- [ ] Final framework: Preact or SolidJS, to be decided after a grid prototype on the TV
- [ ] Final server hardware after the laptop trial (Intel N100/N150 mini PC if transcoding is needed, otherwise even a Raspberry Pi 5)
- [ ] A single Jellyfin user for the household or separate profiles
- [ ] Default audio and subtitle language
- [ ] If and when to open access from outside the home (VPN such as Tailscale or WireGuard)

## Sources

- [VIDAA: partners and HTML5 support](https://www.vidaa.com/?p=20)
- [VIDAA: technical guide to web apps](https://www.vidaa.com/wp-content/uploads/2020/12/WebApp_Development_Guide_for_VIDAA.pdf)
- [Lightning 3 and Blits: performance on TVs](https://lightningjs.io/blogs/roadToPerformance.html)
- [Norigin Spatial Navigation](https://github.com/noriginmedia/norigin-spatial-navigation)
- [preact-spatial-navigation](https://app.unpkg.com/preact-spatial-navigation@1.3.1/files/README.md)
- [solidjs-spatial-navigation](https://github.com/LampaWebDev/solidjs-spatial-navigation)

