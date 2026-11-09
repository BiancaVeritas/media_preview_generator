"""A preview is judged by the VIDEO, because thumbnails are pictures.

The recorded runtime describes the container, which counts the sound: an outro or ED over a fade, or a runtime record
left behind by an older copy of the file, both make it longer than the picture. Demanding thumbnails for that extra
stretch asks for frames that cannot exist, so the preview can never pass and is rebuilt on every run. This module pins
the rule that replaced that: measure where the picture stops, and judge the frame count against that.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from media_preview_generator.bif_reader import BIF_MAGIC
from media_preview_generator.previews_audit import (
    AUDIO_ONLY_TAIL_MIN_S,
    _expected_frames,
    _probe_video_end,
    check_preview,
)


def _write_bif(path: Path, frames: int, interval_ms: int = 10_000) -> Path:
    payload = b"\xff\xd8\xff\xd9"
    body = payload * frames
    first = 64 + (frames + 1) * 8
    index = bytearray()
    for number in range(frames):
        index += struct.pack("<II", number, first + number * len(payload))
    index += struct.pack("<II", 0xFFFFFFFF, first + len(body))
    header = bytearray(BIF_MAGIC) + struct.pack("<III", 0, frames, interval_ms)
    header += b"\x00" * (64 - len(header))
    path.write_bytes(bytes(header) + bytes(index) + body)
    return path


@pytest.fixture
def media(tmp_path):
    def make(name: str = "film.strm") -> str:
        path = tmp_path / name
        path.write_text("http://share.invalid/x", encoding="utf-8")
        return str(path)

    return make


def _stub_video_end(monkeypatch, video_end):
    monkeypatch.setattr(
        "media_preview_generator.previews_audit._probe_video_end", lambda _path: video_end
    )


# --- the real files this was written for ----------------------------------------------------------

def test_a_picture_that_stops_before_the_container_is_complete(tmp_path, monkeypatch, media):
    """GLOD-0158: 94 frames for 15.7 min of picture, container 16.4 min (a 43s ED). That is complete."""
    source = media()
    preview = _write_bif(tmp_path / "film-320-10.bif", 94)
    _stub_video_end(monkeypatch, 941.2)

    assert check_preview(source, str(preview), runtime_s=984.15) is None


def test_a_stale_recorded_runtime_is_judged_by_the_picture(tmp_path, monkeypatch, media):
    """DABR-0256: record says 53 min, the picture runs 46, and the preview covers all 46."""
    source = media()
    preview = _write_bif(tmp_path / "film-320-10.bif", 275)
    _stub_video_end(monkeypatch, 2748.7)

    assert check_preview(source, str(preview), runtime_s=3200.4) is None


def test_a_long_audio_only_tail_is_complete_too(tmp_path, monkeypatch, media):
    """DANM-8952: 93 frames for 15.5 min of picture with a 2 min tail."""
    source = media()
    preview = _write_bif(tmp_path / "film-320-10.bif", 93)
    _stub_video_end(monkeypatch, 928.0)

    assert check_preview(source, str(preview), runtime_s=1037.4) is None


# --- the cases that must still be reported --------------------------------------------------------

def test_a_preview_short_of_the_picture_is_reported(tmp_path, monkeypatch, media):
    """A real 30-minute picture with a preview covering only 16 minutes: the run stopped part-way."""
    source = media()
    preview = _write_bif(tmp_path / "film-320-10.bif", 93)
    _stub_video_end(monkeypatch, 1798.0)

    problem = check_preview(source, str(preview), runtime_s=1800.0)

    assert problem is not None


def test_a_one_frame_preview_is_reported_whatever_the_picture_length(tmp_path, monkeypatch, media):
    source = media()
    preview = _write_bif(tmp_path / "film-320-10.bif", 1)
    _stub_video_end(monkeypatch, 7200.0)

    problem = check_preview(source, str(preview), runtime_s=7200.0)

    assert problem is not None


def test_too_many_frames_is_still_reported(tmp_path, monkeypatch, media):
    """The >150% rule is untouched by any of this."""
    source = media()
    runtime = 7200.0
    expected = _expected_frames(runtime, 10)
    preview = _write_bif(tmp_path / "film-320-10.bif", int(expected * 1.5) + 1)
    _stub_video_end(monkeypatch, runtime)

    assert check_preview(source, str(preview), runtime_s=runtime) is not None


# --- when the probe can't answer ------------------------------------------------------------------

def test_an_unreadable_picture_falls_back_to_reporting(tmp_path, monkeypatch, media):
    """No measurement either way: keep the old behaviour rather than silently calling it healthy."""
    source = media()
    preview = _write_bif(tmp_path / "film-320-10.bif", 93)
    _stub_video_end(monkeypatch, None)

    assert check_preview(source, str(preview), runtime_s=1800.0) is not None


def test_a_healthy_preview_never_probes_the_video(tmp_path, monkeypatch, media):
    """The probe is for previews that already look short; a good one costs no extra request."""
    source = media()
    preview = _write_bif(tmp_path / "film-320-10.bif", 180)
    monkeypatch.setattr(
        "media_preview_generator.previews_audit._probe_video_end",
        lambda *_a: pytest.fail("a healthy preview must not trigger the probe"),
    )

    assert check_preview(source, str(preview), runtime_s=1800.0) is None


# --- the probe reads only the video stream --------------------------------------------------------

def test_the_probe_asks_ffprobe_for_the_video_stream_only(tmp_path, monkeypatch):
    """One request, one stream: the sound's timestamps can't influence a thumbnail count."""
    source = tmp_path / "film.strm"
    source.write_text("http://share.invalid/x", encoding="utf-8")
    calls: list[list[str]] = []
    proc = type("P", (), {"returncode": 0, "stdout": "0.0\n10.0\n928.0", "stderr": ""})()

    def fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        return proc

    monkeypatch.setattr("media_preview_generator.previews_audit.subprocess.run", fake_run)

    assert _probe_video_end(str(source)) == 928.0
    assert len(calls) == 1
    assert "v:0" in calls[0], "the video stream is named explicitly"
    assert "a:0" not in calls[0], "the audio stream is never asked for"


def test_the_probe_takes_the_latest_timestamp(tmp_path, monkeypatch):
    source = tmp_path / "film.strm"
    source.write_text("http://share.invalid/x", encoding="utf-8")
    proc = type("P", (), {"returncode": 0, "stdout": "0.0\n100.0\n928.0\nN/A\n55.0", "stderr": ""})()
    monkeypatch.setattr(
        "media_preview_generator.previews_audit.subprocess.run", lambda *_a, **_k: proc
    )

    assert _probe_video_end(str(source)) == 928.0


def test_a_failed_ffprobe_gives_no_answer(tmp_path, monkeypatch):
    source = tmp_path / "film.strm"
    source.write_text("http://share.invalid/x", encoding="utf-8")
    proc = type("P", (), {"returncode": 1, "stdout": "", "stderr": "boom"})()
    monkeypatch.setattr(
        "media_preview_generator.previews_audit.subprocess.run", lambda *_a, **_k: proc
    )

    assert _probe_video_end(str(source)) is None


def test_an_unreachable_strm_is_not_an_error(tmp_path):
    """A broken .strm must not take the audit down with it."""
    source = tmp_path / "missing.strm"
    source.write_text("", encoding="utf-8")

    assert _probe_video_end(str(source)) is None


def test_the_frame_count_matches_what_the_sampler_writes():
    """``floor(runtime/interval) + 1``: samples at 0, 10, 20 …; round(9.6) would ask for one extra."""
    assert _expected_frames(96.0, 10) == 10.0
    assert _expected_frames(100.0, 10) == 11.0
    assert _expected_frames(2748.79, 10) == 275.0


def test_a_short_clip_gets_one_frame_of_slack():
    """9 of 10 frames is 90% — a fail by share, though the sampler may not emit the tenth."""
    source_frames = 96.0
    expected = _expected_frames(source_frames, 10)
    from media_preview_generator.previews_audit import _covers_its_run

    assert _covers_its_run(9, expected)
    assert not _covers_its_run(8, expected)


def test_the_tail_constant_is_only_a_wording_threshold_now():
    """It no longer decides anything: the video's end is the yardstick either way. It only chooses the sentence."""
    assert AUDIO_ONLY_TAIL_MIN_S >= 10
