"""A file whose video stops before its audio is not a broken preview.

Plenty of releases end with an ED/outro over a fade: the picture stops minutes before the container does. Judging
those by the container's duration demands thumbnails for a stretch with no picture, so the preview can never pass
and is rebuilt on every run — forever. The check now measures the streams' real ends, but only for a file that
already looks short.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from media_preview_generator.bif_reader import BIF_MAGIC
from media_preview_generator.previews_audit import _video_ends_before_audio, check_preview


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


def _stub_stream_ends(monkeypatch, video_end, audio_end):
    """Stub the single combined probe that reports where each stream really stops."""
    from media_preview_generator.previews_audit import _StreamEnds

    def fake(_path):
        if video_end is None:
            return None
        return _StreamEnds(video_end=video_end, audio_end=audio_end)

    monkeypatch.setattr("media_preview_generator.previews_audit._probe_stream_ends", fake)


# --- the real reported file: container 1037s, video 928s, 93 frames -------------------------------

def test_an_audio_only_tail_is_not_a_short_preview(tmp_path, monkeypatch, media):
    """928s of video at a 10s interval wants ~93 frames; 93 is exactly right, so nothing is wrong."""
    source = media()
    preview = _write_bif(tmp_path / "film-320-10.bif", 93)
    _stub_stream_ends(monkeypatch, video_end=928.0, audio_end=1037.4)

    assert check_preview(source, str(preview), runtime_s=1037.417) is None


def test_a_genuinely_short_preview_is_still_reported(tmp_path, monkeypatch, media):
    """Video and audio end together: the runtime is the truth and 93 of 176 frames really is short."""
    source = media()
    preview = _write_bif(tmp_path / "film-320-10.bif", 93)
    _stub_stream_ends(monkeypatch, video_end=1760.0, audio_end=1765.0)

    problem = check_preview(source, str(preview), runtime_s=1760.0)

    assert problem is not None
    assert problem.frames == 93


def test_a_file_that_really_stops_short_is_reported(tmp_path, monkeypatch, media):
    """The preview covers only part of what the file itself holds: that is a failed run, not a stale record."""
    source = media()
    preview = _write_bif(tmp_path / "film-320-10.bif", 93)
    # The file really is 30 min long (both streams reach 1800s); its preview stops at 16 min.
    _stub_stream_ends(monkeypatch, video_end=1798.0, audio_end=1800.0)

    problem = check_preview(source, str(preview), runtime_s=1800.0)

    assert problem is not None


def test_a_stale_recorded_runtime_is_reported_healthy(tmp_path, monkeypatch, media):
    """The record says 53 min, the file really holds 46, and the preview covers all 46: nothing to rebuild."""
    source = media()
    preview = _write_bif(tmp_path / "film-320-10.bif", 275)
    _stub_stream_ends(monkeypatch, video_end=2748.7, audio_end=2748.8)

    assert check_preview(source, str(preview), runtime_s=3200.4) is None


def test_a_preview_short_by_both_measures_is_still_reported(tmp_path, monkeypatch, media):
    """A shorter file is no excuse for a preview that stops well before even the real content."""
    source = media()
    preview = _write_bif(tmp_path / "film-320-10.bif", 100)
    _stub_stream_ends(monkeypatch, video_end=2748.7, audio_end=2748.8)

    assert check_preview(source, str(preview), runtime_s=3200.4) is not None


def test_a_tail_under_the_threshold_is_not_treated_as_audio_only(tmp_path, monkeypatch, media):
    """A minute of lag is normal stream rounding; it must not excuse a real shortfall."""
    source = media()
    preview = _write_bif(tmp_path / "film-320-10.bif", 93)
    _stub_stream_ends(monkeypatch, video_end=1720.0, audio_end=1760.0)

    problem = check_preview(source, str(preview), runtime_s=1760.0)

    assert problem is not None


def test_a_healthy_preview_never_probes_the_streams(tmp_path, monkeypatch, media):
    """The whole point of doing this last: a good preview costs no extra ffprobe."""
    source = media()
    preview = _write_bif(tmp_path / "film-320-10.bif", 176)
    monkeypatch.setattr(
        "media_preview_generator.previews_audit._video_ends_before_audio",
        lambda *_a: pytest.fail("a healthy preview must not trigger the stream-end probe"),
    )

    assert check_preview(source, str(preview), runtime_s=1760.0) is None


def test_an_unreadable_stream_falls_back_to_reporting(tmp_path, monkeypatch, media):
    """No answer either way: keep the old behaviour rather than silently calling it healthy."""
    source = media()
    preview = _write_bif(tmp_path / "film-320-10.bif", 93)
    monkeypatch.setattr(
        "media_preview_generator.previews_audit._video_ends_before_audio", lambda *_a: None
    )

    assert check_preview(source, str(preview), runtime_s=1760.0) is not None


def test_the_helper_needs_the_audio_to_run_on(tmp_path, monkeypatch):
    """Video and audio ending together is not an audio-only tail; a long gap between them is."""
    source = tmp_path / "film.strm"
    source.write_text("http://share.invalid/x", encoding="utf-8")

    def run_with(video_end, audio_end):
        rows = [f"0,{video_end}", f"1,{audio_end}"]
        proc = type("P", (), {"returncode": 0, "stdout": "\n".join(rows), "stderr": ""})()
        monkeypatch.setattr(
            "media_preview_generator.previews_audit.subprocess.run", lambda *_a, **_k: proc
        )
        return _video_ends_before_audio(str(source))

    assert run_with(900.0, 902.0) is None, "they end together: the runtime is the truth"
    assert run_with(900.0, 1200.0) == 900.0, "a long audio-only tail: measure by the video"


def test_both_ends_come_from_a_single_probe(tmp_path, monkeypatch):
    """One HTTP request per problem file: over a cloud link an extra call may trip rate limiting.

    ``-select_streams`` rejects a comma list ("Invalid stream specifier: v:0,a:0"), so the command asks for every
    stream's packets once and splits them by stream index.
    """
    source = tmp_path / "film.strm"
    source.write_text("http://share.invalid/x", encoding="utf-8")
    calls: list[list[str]] = []
    proc = type("P", (), {"returncode": 0, "stdout": "0,928.0\n1,1037.0", "stderr": ""})()

    def fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        return proc

    monkeypatch.setattr("media_preview_generator.previews_audit.subprocess.run", fake_run)

    assert _video_ends_before_audio(str(source)) == 928.0
    assert len(calls) == 1, "the two stream ends must come from one ffprobe run"
    assert "-select_streams" not in calls[0], "a comma list is rejected by ffprobe"
    assert "packet=stream_index,pts_time" in calls[0]


# --- frame counting: no rounding, and a short clip gets a frame of slack ---------------------------


def test_the_expected_count_is_the_frames_the_sampler_really_writes():
    """``fps=1/10`` samples at 0, 10, 20 … so the count is ``floor(runtime/interval) + 1`` — no rounding up."""
    from media_preview_generator.previews_audit import _expected_frames

    # 96s samples at 0,10,...,90 -> 10 frames (round(9.6) also gives 10, but for the wrong reason)
    assert _expected_frames(96.0, 10) == 10.0
    # 100s samples at 0,10,...,100 -> 11 frames; round(10.0) would say 10 and undercount by one
    assert _expected_frames(100.0, 10) == 11.0
    # 95.99s: the 100th second never arrives, so 0..90 -> 10 frames
    assert _expected_frames(95.99, 10) == 10.0
    assert _expected_frames(2748.79, 10) == 275.0


def test_a_short_clip_is_judged_by_frames_not_by_share(tmp_path, monkeypatch, media):
    """9 of 10 frames is 90% — a fail by share, but the sampler may not emit the tenth."""
    source = media()
    preview = _write_bif(tmp_path / "film-320-10.bif", 9)
    monkeypatch.setattr(
        "media_preview_generator.previews_audit._probe_stream_ends", lambda _p: None
    )

    assert check_preview(source, str(preview), runtime_s=96.0) is None


def test_a_short_clip_missing_two_frames_is_reported(tmp_path, monkeypatch, media):
    """Only the one frame the generator may not emit is excused; two frames is content that was not read."""
    source = media()
    preview = _write_bif(tmp_path / "film-320-10.bif", 8)
    monkeypatch.setattr(
        "media_preview_generator.previews_audit._probe_stream_ends", lambda _p: None
    )

    assert check_preview(source, str(preview), runtime_s=96.0) is not None


def test_a_film_still_allows_five_percent(tmp_path, monkeypatch, media):
    """The frame slack must not tighten the long-file rule: 5% of a 46-minute film is 14 frames."""
    source = media()
    preview = _write_bif(tmp_path / "film-320-10.bif", 262)
    monkeypatch.setattr(
        "media_preview_generator.previews_audit._probe_stream_ends", lambda _p: None
    )

    assert check_preview(source, str(preview), runtime_s=2748.79) is None


def test_the_tail_threshold_sits_between_the_two_real_populations():
    """Measured: an intact (or truncated) file's streams end within 0.1s; real audio-only tails ran 43s+."""
    from media_preview_generator.previews_audit import AUDIO_ONLY_TAIL_MIN_S, _StreamEnds

    assert AUDIO_ONLY_TAIL_MIN_S >= 10, "must not treat ordinary stream rounding as an audio-only tail"
    assert AUDIO_ONLY_TAIL_MIN_S <= 43, "must catch a 43s outro, the shortest seen in a real library"

    # A whole file, and a truncated one: both streams end together.
    assert not _StreamEnds(video_end=1612.3, audio_end=1612.4).is_audio_only_tail
    assert not _StreamEnds(video_end=300.1, audio_end=300.0).is_audio_only_tail
    # Real tails from a library.
    assert _StreamEnds(video_end=941.2, audio_end=984.1).is_audio_only_tail
    assert _StreamEnds(video_end=928.1, audio_end=1037.4).is_audio_only_tail


def test_a_short_audio_tail_is_enough_to_judge_by_the_picture(tmp_path, monkeypatch, media):
    """GLOD-0158: a 43s outro, 94 frames for 15.7 min of picture, judged complete."""
    source = media()
    preview = _write_bif(tmp_path / "film-320-10.bif", 94)
    _stub_stream_ends(monkeypatch, video_end=941.2, audio_end=984.1)

    assert check_preview(source, str(preview), runtime_s=984.15) is None
