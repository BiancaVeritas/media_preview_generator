"""The preview audit: a .bif whose frames can't cover its video's runtime."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from media_preview_generator.bif_reader import BIF_MAGIC
from media_preview_generator.previews_audit import check_preview, scan_folder

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
    assert problem.expected_frames == pytest.approx(241)


def test_a_complete_preview_passes(tmp_path, monkeypatch, media):
    source, _ = media("film.mkv", 2400)
    preview = _write_bif(tmp_path / "film-320-10.bif", 240)
    _stub_runtime(monkeypatch, 2400)

    assert check_preview(str(source), str(preview)) is None


def test_a_preview_that_lost_a_few_frames_at_the_tail_passes(tmp_path, monkeypatch, media):
    """A decoder error on the last packets costs a frame or two; that is still a good preview."""
    source, _ = media("film.mkv", 2400)
    preview = _write_bif(tmp_path / "film-320-10.bif", 238)
    _stub_runtime(monkeypatch, 2400)

    assert check_preview(str(source), str(preview)) is None


def test_a_preview_that_stopped_fifteen_minutes_early_is_reported(tmp_path, monkeypatch, media):
    """On a two-hour film, 15 minutes is 87%: below the share, so it is caught."""
    source, _ = media("film.mkv", 7200)
    preview = _write_bif(tmp_path / "film-320-10.bif", 630)
    _stub_runtime(monkeypatch, 7200)

    problem = check_preview(str(source), str(preview))

    assert problem is not None
    assert "15" in problem.reason


def test_a_three_hour_film_that_stopped_eight_minutes_early_is_reported(tmp_path, monkeypatch, media):
    """8 minutes of 180 is 95.5% by share, but the shortfall rule catches it."""
    source, _ = media("film.mkv", 10_800)
    preview = _write_bif(tmp_path / "film-320-10.bif", 1032)
    _stub_runtime(monkeypatch, 10_800)

    problem = check_preview(str(source), str(preview))

    assert problem is not None
    assert "8" in problem.reason


def test_a_few_minutes_short_is_normal(tmp_path, monkeypatch, media):
    """The stated runtime runs past the video stream, and the last frame is up to one interval early."""
    source, _ = media("film.mkv", 2400)
    preview = _write_bif(tmp_path / "film-320-10.bif", 239)
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


def test_a_short_clip_is_judged_by_its_frames_like_any_other(tmp_path, monkeypatch, media):
    """A 30s clip asks for 4 frames: 4 passes, 1 is genuinely short, and the old 'skip anything under a minute' rule
    would have hidden the latter.

    Real 3D loop clips of 7-50s with 1-5 frames are legitimate; the runtime sources (record, ffprobe, video stream)
    already guarantee the duration, so no length-based exemption is needed — or wanted.
    """
    source, _ = media("clip.mkv", 30)
    _stub_runtime(monkeypatch, 30)

    complete = _write_bif(tmp_path / "complete-320-10.bif", 4)
    assert check_preview(str(source), str(complete)) is None

    short = _write_bif(tmp_path / "short-320-10.bif", 1)
    assert check_preview(str(source), str(short)) is not None


def test_an_unknown_runtime_no_longer_hides_a_truncated_preview(tmp_path, monkeypatch, media):
    """A .strm link that 403s used to make the audit silently call a 1-frame preview healthy.

    With no usable runtime at all, a preview that only covers the opening is still recognisably wrong, so it is
    reported rather than skipped. This is the case the six real broken BIFs landed in.
    """
    source, _ = media("film.mkv", 2400)
    preview = _write_bif(tmp_path / "film-320-10.bif", 1)
    _stub_runtime(monkeypatch, None)

    problem = check_preview(str(source), str(preview))

    assert problem is not None
    assert problem.frames == 1
    assert problem.expected_frames is None


def test_a_known_runtime_is_used_without_probing(tmp_path, monkeypatch, media):
    """A runtime the caller already has (server record / json) must not trigger a network probe."""
    source, _ = media("film.strm", 2400)
    preview = _write_bif(tmp_path / "film-320-10.bif", 1)
    monkeypatch.setattr(
        "media_preview_generator.previews_audit._runtime_seconds",
        lambda _path: pytest.fail("the .strm link must not be probed when a runtime is already known"),
    )

    problem = check_preview(str(source), str(preview), runtime_s=2400)

    assert problem is not None and problem.expected_frames == pytest.approx(241)


def test_a_good_preview_with_a_known_runtime_passes(tmp_path, monkeypatch, media):
    """The json-first path must still let a complete preview through."""
    source, _ = media("film.strm", 2400)
    preview = _write_bif(tmp_path / "film-320-10.bif", 240)
    monkeypatch.setattr(
        "media_preview_generator.previews_audit._runtime_seconds", lambda _path: 2400, raising=True
    )

    assert check_preview(str(source), str(preview), runtime_s=2400) is None


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


class TestOverCount:
    """A BIF holding far more frames than its runtime has intervals (an old FFmpeg repeating one picture)."""

    def test_a_bif_with_far_too_many_frames_is_reported(self, tmp_path, monkeypatch, media):
        source, _ = media("film.mkv", 7200)
        preview = _write_bif(tmp_path / "film-320-10.bif", 7200)  # one frame a second, not every ten
        _stub_runtime(monkeypatch, 7200)

        problem = check_preview(str(source), str(preview))

        assert problem is not None
        assert "7200" in problem.reason
        assert "720" in problem.reason

    def test_just_over_the_ceiling_is_reported(self, tmp_path, monkeypatch, media):
        source, _ = media("film.mkv", 600)
        preview = _write_bif(tmp_path / "film-320-10.bif", 95)  # 60 expected, 158%
        _stub_runtime(monkeypatch, 600)

        assert check_preview(str(source), str(preview)) is not None

    def test_a_complete_preview_is_not_called_excessive(self, tmp_path, monkeypatch, media):
        source, _ = media("film.mkv", 600)
        preview = _write_bif(tmp_path / "film-320-10.bif", 61)  # 60 expected plus a tail frame
        _stub_runtime(monkeypatch, 600)

        assert check_preview(str(source), str(preview)) is None

    def test_the_ceiling_is_150_percent(self):
        from media_preview_generator.previews_audit import MAX_HEALTHY_FRAME_SHARE

        assert MAX_HEALTHY_FRAME_SHARE == 1.5
