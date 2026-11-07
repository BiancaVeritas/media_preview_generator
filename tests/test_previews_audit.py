"""The preview audit: a .bif whose frames can't cover its video's runtime."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from media_preview_generator.bif_reader import BIF_MAGIC
from media_preview_generator.previews_audit import (
    MIN_HEALTHY_FRAME_SHARE,
    check_preview,
    scan_folder,
)

INTERVAL_MS = 10_000


def _write_bif(path: Path, frames: int, interval_ms: int = INTERVAL_MS) -> Path:
    """A structurally valid BIF with ``frames`` tiny JPEGs in it."""
    payload = b"\xff\xd8\xff\xd9"
    body = payload * frames
    first = 64 + (frames + 1) * 8
    offsets = [first + index * len(payload) for index in range(frames)]
    index = bytearray()
    for number, offset in enumerate(offsets):
        index += struct.pack("<II", number, offset)
    index += struct.pack("<II", 0xFFFFFFFF, first + len(body))
    header = bytearray(BIF_MAGIC)
    header += struct.pack("<III", 0, frames, interval_ms)
    header += b"\x00" * (64 - len(header))
    path.write_bytes(bytes(header) + bytes(index) + body)
    return path


@pytest.fixture
def media(tmp_path: Path):
    """A file the audit can read a runtime from, without needing a real video."""

    def make(name: str, runtime_s: float) -> tuple[Path, Path]:
        path = tmp_path / name
        path.write_bytes(b"not decoded: the audit reads the runtime through a stub")
        return path, path

    return make


def _stub_runtime(monkeypatch, runtime_s: float) -> None:
    monkeypatch.setattr(
        "media_preview_generator.previews_audit._runtime_seconds", lambda _path: runtime_s, raising=True
    )


def test_a_one_frame_preview_of_a_long_film_is_reported(tmp_path, monkeypatch, media):
    source, _ = media("film.mkv", 2400)
    preview = _write_bif(tmp_path / "film-320-10.bif", 1)
    _stub_runtime(monkeypatch, 2400)

    problem = check_preview(str(source), str(preview))

    assert problem is not None
    assert problem.frames == 1
    assert problem.expected_frames == pytest.approx(240)


def test_a_complete_preview_passes(tmp_path, monkeypatch, media):
    source, _ = media("film.mkv", 2400)
    preview = _write_bif(tmp_path / "film-320-10.bif", 240)
    _stub_runtime(monkeypatch, 2400)

    assert check_preview(str(source), str(preview)) is None


def test_a_preview_that_lost_its_tail_passes(tmp_path, monkeypatch, media):
    source, _ = media("film.mkv", 2400)
    preview = _write_bif(tmp_path / "film-320-10.bif", int(240 * (MIN_HEALTHY_FRAME_SHARE + 0.1)))
    _stub_runtime(monkeypatch, 2400)

    assert check_preview(str(source), str(preview)) is None


def test_an_empty_preview_is_reported(tmp_path, monkeypatch, media):
    source, _ = media("film.mkv", 600)
    preview = _write_bif(tmp_path / "film-320-10.bif", 0)
    _stub_runtime(monkeypatch, 600)

    problem = check_preview(str(source), str(preview))

    assert problem is not None
    assert "0" in problem.reason


def test_a_corrupt_preview_is_reported(tmp_path, monkeypatch, media):
    source, _ = media("film.mkv", 600)
    preview = tmp_path / "film-320-10.bif"
    preview.write_bytes(b"not a bif at all")
    _stub_runtime(monkeypatch, 600)

    problem = check_preview(str(source), str(preview))

    assert problem is not None and problem.frames == 0


def test_a_short_clip_is_skipped(tmp_path, monkeypatch, media):
    """Under a minute the frame count can't tell a good preview from a bad one."""
    source, _ = media("clip.mkv", 30)
    preview = _write_bif(tmp_path / "clip-320-10.bif", 1)
    _stub_runtime(monkeypatch, 30)

    assert check_preview(str(source), str(preview)) is None


def test_an_unknown_runtime_is_skipped(tmp_path, monkeypatch, media):
    source, _ = media("film.mkv", 2400)
    preview = _write_bif(tmp_path / "film-320-10.bif", 1)
    _stub_runtime(monkeypatch, None)

    assert check_preview(str(source), str(preview)) is None


def test_the_interval_comes_from_the_file_name(tmp_path, monkeypatch, media):
    source, _ = media("film.mkv", 1200)
    preview = _write_bif(tmp_path / "film-320-2.bif", 600, interval_ms=2000)
    _stub_runtime(monkeypatch, 1200)

    assert check_preview(str(source), str(preview)) is None


def test_scan_folder_finds_only_the_broken_one(tmp_path, monkeypatch):
    _stub_runtime(monkeypatch, 2400)
    for name in ("good.mkv", "bad.mkv"):
        (tmp_path / name).write_bytes(b"x")
    _write_bif(tmp_path / "good-320-10.bif", 240)
    _write_bif(tmp_path / "bad-320-10.bif", 1)
    _write_bif(tmp_path / "orphan-320-10.bif", 1)  # no source beside it: not the audit's business

    problems = scan_folder(str(tmp_path))

    assert [Path(p.preview_path).name for p in problems] == ["bad-320-10.bif"]
