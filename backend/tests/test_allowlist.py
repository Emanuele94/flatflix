"""Tests for the pure per-file allowlist (FILT-02, D-14)."""

from app.download.allowlist import FileDecision, TorrentFile, decide

# Verbatim qBittorrent 5.2.4 `torrents/files` rows (research, Code Examples).
SINTEL_VIDEO_ROW = {"index": 5, "priority": 1, "size": 129241752, "name": "Sintel/Sintel.mp4"}
SINTEL_POSTER_ROW = {"index": 10, "priority": 0, "size": 46115, "name": "Sintel/poster.jpg"}
SINTEL_SUBTITLE_ROW = {"index": 6, "priority": 1, "size": 30000, "name": "Sintel/Sintel.en.srt"}


def test_real_torrent_file_list_is_split_into_keep_and_zero_indexes():
    files = [
        TorrentFile.from_qbit(SINTEL_VIDEO_ROW),
        TorrentFile.from_qbit(SINTEL_POSTER_ROW),
        TorrentFile.from_qbit(SINTEL_SUBTITLE_ROW),
    ]

    decision = decide(files)

    assert decision == FileDecision(accept=True, keep_ids=(5, 6), zero_ids=(10,), reason=None)


def test_from_qbit_maps_index_name_size_priority():
    file = TorrentFile.from_qbit(SINTEL_VIDEO_ROW)

    assert file == TorrentFile(index=5, name="Sintel/Sintel.mp4", size=129241752, priority=1)
