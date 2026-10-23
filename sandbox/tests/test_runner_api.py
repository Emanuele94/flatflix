"""The runner's HTTP contract, driven end to end against a stub firecracker.

POST /probe resolves a path under the quarantine root only, boots one VM per
request and answers plain facts; the runner never judges them (D-69, D-70).
"""

from __future__ import annotations


def test_probe_boots_one_vm_and_answers_the_facts_contract(runner, stub_firecracker):
    status, body = runner.probe("Film/Movie/movie.mkv")

    assert status == 200
    assert body["status"] == "ok"
    assert body["reason"] is None
    assert body["ffprobe_exit"] == 0
    assert body["size_bytes"] == 2097152
    assert body["ffmpeg"] == "8.1.2-r0"
    assert body["format"]["format_name"] == "matroska,webm"
    video = body["streams"][0]
    assert (video["codec_type"], video["codec_name"]) == ("video", "h264")
    assert video["attached_pic"] is False

    configs = stub_firecracker.configs()
    assert len(configs) == 1
    assert "network-interfaces" not in configs[0]
    assert len(configs[0]["drives"]) == 3
    assert all(drive["is_read_only"] is True for drive in configs[0]["drives"])
