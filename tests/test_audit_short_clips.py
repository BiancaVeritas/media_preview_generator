"""Short clips are legitimate files, not truncated reads.

A 3D loop of 7-50 seconds with 1-5 thumbnails is exactly what a complete run produces. The audit used to exempt
everything under a minute (hiding real shortfalls) or flag every short network read (rebuilding every loop forever).
Both are gone: the duration comes from a record, ffprobe, or the video stream, and the frame count is judged against
it like any other file.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from media_preview_generator.bif_reader import BIF_MAGIC
from media_preview_generator.previews_audit import check_preview


def _write_bif(path: Path, frames: int) -> Path:
    payload = b"\xff\xd8\xff\xd9"
    body = payload * frames
    first = 64 + (frames + 1) * 8
    index = bytearray()
    for number in range(frames):
        index += struct.pack("<II", number, first + number * len(payload))
    index += struct.pack("<II", 0xFFFFFFFF, first + len(body))
    header = bytearray(BIF_MAGIC) + struct.pack("<III", 0, frames, 10_000)
    header += b"\x00" * (64 - len(header))
    path.write_bytes(bytes(header) + bytes(index) + body)
    return path


@pytest.fixture
def media(tmp_path):
    def make(name: str = "clip.strm") -> str:
        path = tmp_path / name
        path.write_text("http://share.invalid/x", encoding="utf-8")
        return str(path)

    return make


# Real measured clips from the 2·3D library: (name, duration, frames a complete run writes)
REAL_CLIPS = [
    ("Tifa Mating Press Loop 1", 7.13, 1),
    ("Floraxis Alice P.9", 23.38, 3),
    ("Nagoonimation Aerith", 49.90, 5),
]


@pytest.mark.parametrize("name,runtime,frames", REAL_CLIPS)
def test_real_short_clips_are_not_reported(tmp_path, monkeypatch, media, name, runtime, frames):
    source = media()
    preview = _write_bif(tmp_path / "clip-320-10.bif", frames)
    monkeypatch.setattr(
        "media_preview_generator.previews_audit._runtime_seconds", lambda _p: runtime
    )

    assert check_preview(str(source), str(preview)) is None, name


@pytest.mark.parametrize("runtime,frames", [(7.13, 1), (23.38, 3), (49.90, 5)])
def test_a_short_clip_that_really_is_short_is_reported(tmp_path, monkeypatch, media, runtime, frames):
    """A genuinely short clip gets no free pass: one frame of a 50s clip is still short."""
    source = media()
    preview = _write_bif(tmp_path / "clip-320-10.bif", 1)
    monkeypatch.setattr(
        "media_preview_generator.previews_audit._runtime_seconds", lambda _p: runtime
    )
    monkeypatch.setattr(
        "media_preview_generator.previews_audit._probe_video_end", lambda _p: runtime
    )

    if frames > 2:  # 3 or 5 expected; 1 frame is a real shortfall
        assert check_preview(str(source), str(preview)) is not None


def test_no_runtime_falls_back_to_the_video_stream(tmp_path, monkeypatch, media):
    """Read no duration anywhere: the video stream's own end decides, so a short clip still passes."""
    source = media()
    preview = _write_bif(tmp_path / "clip-320-10.bif", 3)
    monkeypatch.setattr(
        "media_preview_generator.previews_audit._runtime_seconds", lambda _p: None
    )
    monkeypatch.setattr(
        "media_preview_generator.previews_audit._probe_video_end", lambda _p: 23.38
    )

    assert check_preview(str(source), str(preview)) is None


def test_no_runtime_and_a_long_video_still_reports_a_one_frame_preview(tmp_path, monkeypatch, media):
    """A 1-frame preview of a long video must not hide behind an unreadable duration."""
    source = media()
    preview = _write_bif(tmp_path / "clip-320-10.bif", 1)
    monkeypatch.setattr(
        "media_preview_generator.previews_audit._runtime_seconds", lambda _p: None
    )
    monkeypatch.setattr(
        "media_preview_generator.previews_audit._probe_video_end", lambda _p: 7200.0
    )

    assert check_preview(str(source), str(preview)) is not None


def test_no_runtime_and_no_video_read_reports_it(tmp_path, monkeypatch, media):
    """Nothing can be measured either way: keep reporting, never silently bless it."""
    source = media()
    preview = _write_bif(tmp_path / "clip-320-10.bif", 1)
    monkeypatch.setattr(
        "media_preview_generator.previews_audit._runtime_seconds", lambda _p: None
    )
    monkeypatch.setattr(
        "media_preview_generator.previews_audit._probe_video_end", lambda _p: None
    )

    assert check_preview(str(source), str(preview)) is not None
