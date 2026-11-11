"""A BIF whose byte layout is broken, even though its frame count looks right.

The index table can be complete while the payload it points at is half-written: a run that died mid-write, a killed
process, a dropped cloud link. Every count-based rule passes such a file, yet the last thumbnails cannot be read at
all. Checking the offsets costs nothing — the index is already parsed — and needs no runtime.
"""

from __future__ import annotations

import struct

import pytest

from media_preview_generator.bif_reader import BIF_MAGIC
from media_preview_generator.previews_audit import _BIF_HEADER_SIZE, inspect_preview


def _valid_bif(frames: int, payload_size: int = 400, interval_ms: int = 10_000) -> bytes:
    """A structurally sound BIF: index and payload agree, every offset inside the file."""
    payload = b"\x11" * payload_size
    first = _BIF_HEADER_SIZE + (frames + 1) * 8
    index = bytearray()
    offsets = [first + number * payload_size for number in range(frames)]
    for number, offset in enumerate(offsets):
        index += struct.pack("<II", number, offset)
    index += struct.pack("<II", 0xFFFFFFFF, first + frames * payload_size)
    header = bytearray(BIF_MAGIC) + struct.pack("<III", 0, frames, interval_ms)
    header += b"\x00" * (_BIF_HEADER_SIZE - len(header))
    return bytes(header) + bytes(index) + payload * frames


@pytest.fixture
def media(tmp_path):
    def make(name: str = "film.strm") -> str:
        path = tmp_path / name
        path.write_text("http://share.invalid/x", encoding="utf-8")
        return str(path)

    return make


def test_a_sound_bif_passes(tmp_path, media):
    # 110s at a 10s interval expects 12 frames (0, 10, ..., 110); 12 covers 120s, so it is complete.
    bif = tmp_path / "film-320-10.bif"
    bif.write_bytes(_valid_bif(12))

    assert inspect_preview(media(), str(bif), runtime_s=110).passed


def test_a_half_written_payload_is_caught(tmp_path, media):
    """Index complete, payload cut in half: the count looks perfect and the last frames are unreadable."""
    bif = tmp_path / "film-320-10.bif"
    raw = _valid_bif(10)
    bif.write_bytes(raw[: len(raw) // 2])

    verdict = inspect_preview(media(), str(bif), runtime_s=110)

    assert not verdict.passed
    assert "超出文件末尾" in verdict.problem.reason


def test_an_offset_inside_the_header_is_caught(tmp_path, media):
    """A corrupt entry pointing at the header rather than the payload."""
    bif = tmp_path / "film-320-10.bif"
    raw = bytearray(_valid_bif(10))
    # The first entry's offset sits right after its 4-byte timestamp.
    raw[_BIF_HEADER_SIZE + 4 : _BIF_HEADER_SIZE + 8] = (10).to_bytes(4, "little")
    bif.write_bytes(bytes(raw))

    verdict = inspect_preview(media(), str(bif), runtime_s=110)

    assert not verdict.passed
    assert "落在文件头部" in verdict.problem.reason


def test_a_last_frame_running_past_the_end_is_caught(tmp_path, media):
    """The end offset claims more bytes than the file holds (a cut tail)."""
    bif = tmp_path / "film-320-10.bif"
    raw = bytearray(_valid_bif(10))
    # The sentinel's end offset is the last 4 bytes of the index: push it past the file.
    end_at = _BIF_HEADER_SIZE + 10 * 8 + 4
    raw[end_at : end_at + 4] = (len(raw) + 500).to_bytes(4, "little")
    bif.write_bytes(bytes(raw))

    verdict = inspect_preview(media(), str(bif), runtime_s=110)

    assert not verdict.passed


def test_the_structure_check_needs_no_runtime(tmp_path, media, monkeypatch):
    """It answers before any probing: a broken file must not cost a network read first."""
    bif = tmp_path / "film-320-10.bif"
    raw = _valid_bif(10)
    bif.write_bytes(raw[: len(raw) // 2])
    monkeypatch.setattr(
        "media_preview_generator.previews_audit._runtime_seconds",
        lambda _p: pytest.fail("a broken BIF must not be probed for a runtime"),
    )

    assert not inspect_preview(media(), str(bif)).passed


def test_a_good_bif_is_still_checked_against_its_runtime(tmp_path, media):
    """The structure check does not short-circuit the real judgement on a sound file."""
    bif = tmp_path / "film-320-10.bif"
    bif.write_bytes(_valid_bif(10))  # 10 frames covers ~100s

    assert not inspect_preview(media(), str(bif), runtime_s=3600).passed, "an hour needs 361 frames"


def test_zero_frames_is_reported_before_the_structure_check(tmp_path, media):
    bif = tmp_path / "film-320-10.bif"
    bif.write_bytes(_valid_bif(0))

    verdict = inspect_preview(media(), str(bif), runtime_s=110)

    assert not verdict.passed
    assert "0 帧" in verdict.problem.reason
