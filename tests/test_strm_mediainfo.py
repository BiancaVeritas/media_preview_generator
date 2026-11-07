"""Reading the runtime StrmAssistant already saved beside a .strm, without touching the link."""

from __future__ import annotations

import json

from media_preview_generator import strm


def test_the_mediainfo_sidecar_supplies_the_runtime(tmp_path):
    video = tmp_path / "CWPBD-144 [1080p].strm"
    video.write_text("http://192.168.31.100:7196/redirect?pickcode=x", encoding="utf-8")
    (tmp_path / "CWPBD-144 [1080p]-mediainfo.json").write_text(
        json.dumps([{"MediaSourceInfo": {"RunTimeTicks": 76957120000}}]), encoding="utf-8"
    )

    assert strm.sidecar_runtime_seconds(str(video)) == 7695.712


def test_no_sidecar_returns_none(tmp_path):
    video = tmp_path / "film.strm"
    video.write_text("http://example.invalid/x", encoding="utf-8")

    assert strm.sidecar_runtime_seconds(str(video)) is None


def test_a_malformed_sidecar_returns_none(tmp_path):
    video = tmp_path / "film.strm"
    video.write_text("http://example.invalid/x", encoding="utf-8")
    (tmp_path / "film-mediainfo.json").write_text("not json", encoding="utf-8")

    assert strm.sidecar_runtime_seconds(str(video)) is None


def test_a_sidecar_without_ticks_returns_none(tmp_path):
    video = tmp_path / "film.strm"
    video.write_text("http://example.invalid/x", encoding="utf-8")
    (tmp_path / "film-mediainfo.json").write_text(json.dumps([{"MediaSourceInfo": {}}]), encoding="utf-8")

    assert strm.sidecar_runtime_seconds(str(video)) is None


def test_non_strm_paths_have_no_sidecar(tmp_path):
    video = tmp_path / "film.mkv"
    video.write_bytes(b"x")

    assert strm.sidecar_runtime_seconds(str(video)) is None
