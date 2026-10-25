# Naming scan test (NAME-01)

Who gives downloaded files their library names: stock Jellyfin on the raw torrent names, or a rename step in the portal? The scan test answers it with data. Raw torrent-style names become 1-second clips at the paths the Phase 2.1 hand-off would create (a single-file torrent in the library root, a folder torrent as `<name>/<file>`), stock Jellyfin scans them with its own parser and TheMovieDb in admin-only Raw Movies and Raw TV libraries, and every name is classified against a hand-confirmed truth label as identified, unidentified or wrong title.

The bar (D-92): relaxed naming is accepted only when at least 90 % of the names are identified and none is a wrong title. Otherwise the rename step wins (D-90 leans that way). TheMovieDb answers change over time, so a table is evidence of the method on the day it ran.

Real torrent names carry scene and site tags and are never published (D-101): only counts and failure classes of the real corpus appear here, and the full table is shown for the synthetic sample of open-licensed titles.

Run it with `python3 scripts/name_scan.py run --corpus <file>`; `report` rewrites this file and `validate-report` checks it.

## Real corpus

Not run yet.

## Synthetic sample

RESULT 10 names: identified 8, unidentified 2, wrong title 0 (80 %)

| Name | Expected | Jellyfin matched | Result |
| --- | --- | --- | --- |
| Big.Buck.Bunny.2008.1080p.BluRay.x264-OPEN | Big Buck Bunny (2008) | Big Buck Bunny (2008) | identified |
| Sintel.2010.720p.WEB-DL.AAC.H264.mkv | Sintel (2010) | Sintel (2010) | identified |
| [OpenGroup] Tears of Steel (2012) [1080p].mkv | Tears of Steel (2012) | Tears of Steel (2012) | identified |
| Elephants.Dream.2006.DVDRip.XviD-OPEN | Elephants Dream (2006) | Elephants Dream (2006) | identified |
| Agent.327.Operation.Barbershop.2017.1080p.WEB-DL | Agent 327: Operation Barbershop (2017) | Agent 327: Operation Barbershop (2017) | identified |
| Cosmos.Laundromat.2015.1080p.mkv | Cosmos Laundromat (2015) | Cosmos Laundromat (2015) | identified |
| Spring.2019.2160p.HDR.HEVC-BLENDER.mkv | Spring (2019) | Spring (2019) | identified |
| Pioneer.One.S01E02.720p.WEB.x264-VODO.mkv | Pioneer One S01E02 | no series | unidentified |
| Pioneer.One.S01.COMPLETE.720p.WEB.x264-VODO | Pioneer One S01E01 | Pioneer One S01E01 | identified |
| Pioneer One - 03 (720p) [VODO].mkv | Pioneer One S01E03 | no series | unidentified |

## Decision

Pending: recorded in .planning/PROJECT.md after the real scan (plan 03-09).
