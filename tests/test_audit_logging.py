"""The preview audit logs every verdict, with the numbers behind it.

A whole-library sweep prints one line per file. That is deliberate: this job exists to answer "did the check run, and
what did it see", and a log that only ever shows failures cannot tell a clean sweep from one that never happened.

Each line carries the measurement — the frames the BIF holds, how much video they cover, the runtime it was judged
against, the frame count that implies, and the signed difference — so a pass is distinguishable from a file that was
never looked at.
"""

from __future__ import annotations

import inspect


def _sweep_block() -> str:
    from media_preview_generator.processing import multi_server

    source = inspect.getsource(multi_server)
    start = source.index("if audit_existing:")
    return source[start : start + 4000]


def test_every_verdict_is_logged_at_info():
    """Both branches of the per-file loop print, at the level the job log shows by default."""
    block = _sweep_block()

    assert 'logger.info("Preview check: {} is sound ({}); left as it is"' in block
    assert '"Preview check: {} is wrong ({}); measured {}; rebuilding it in this run"' in block
    assert "logger.debug" not in block


def test_a_sound_line_carries_the_measurement():
    """The whole point: a pass says what it measured, not just that it passed."""
    block = _sweep_block()

    assert "verdict.summary()" in block


def test_a_finding_line_carries_the_measurement_too():
    block = _sweep_block()
    wrong = block[block.index("is wrong"):]
    assert "verdict.summary()" in wrong


def test_no_environment_variable_is_involved():
    """The user asked for the detail by default; a switch would just be one more thing to set."""
    from media_preview_generator.jobs import dispatcher
    from media_preview_generator.processing import multi_server

    for source in (inspect.getsource(multi_server), inspect.getsource(dispatcher)):
        assert "PREVIEW_AUDIT_VERBOSE" not in source
        assert "audit_verbose" not in source


def test_the_sweep_announces_itself():
    from media_preview_generator.jobs import dispatcher

    source = inspect.getsource(dispatcher)
    assert "Preview check enabled:" in source
    assert "verdict is logged" in source
    assert "rebuilt in this run" in source


def test_the_summary_shows_runtime_frames_and_difference():
    """The numbers a reader needs to understand a verdict without opening the file."""
    from media_preview_generator.previews_audit import PreviewVerdict

    complete = PreviewVerdict(
        problem=None,
        frames=94,
        interval_s=10,
        covered_s=930.0,
        runtime_s=941.23,
        expected_frames=95.0,
        runtime_source="video stream",
    )
    line = complete.summary()

    assert "94 frames" in line
    assert "15:30.0" in line  # 930s
    assert "95 expected" in line
    assert "15:41.2" in line  # 941.23s
    assert "video stream" in line
    assert "-1 frames" in line


def test_a_short_clip_reads_in_minutes_and_seconds_not_fractions():
    """23 seconds is "0:23.4", never "0.4 min"."""
    from media_preview_generator.previews_audit import PreviewVerdict

    verdict = PreviewVerdict(
        problem=None,
        frames=3,
        interval_s=10,
        covered_s=30.0,
        runtime_s=23.4,
        expected_frames=3.0,
        runtime_source="probe",
    )

    assert "0:30.0" in verdict.summary()
    assert "0:23.4" in verdict.summary()
    assert " min)" not in verdict.summary()


def test_a_verdict_without_a_runtime_says_so():
    from media_preview_generator.previews_audit import PreviewVerdict

    verdict = PreviewVerdict(
        problem=None,
        frames=5,
        interval_s=10,
        covered_s=50.0,
        runtime_s=None,
        expected_frames=None,
        runtime_source="unknown",
    )

    assert "no runtime readable" in verdict.summary()


def test_the_check_itself_prints_nothing(tmp_path, monkeypatch):
    """One line per file: the caller logs the verdict, so ``inspect_preview`` must stay silent.

    A second line carrying the same "Preview check:" prefix read as a second file being checked. Asserted on real
    output rather than on the source text, since a comment can mention the prefix without logging anything.
    """
    import struct

    from loguru import logger

    from media_preview_generator.bif_reader import BIF_MAGIC
    from media_preview_generator.previews_audit import inspect_preview

    frames = 12
    payload = b"\x11" * 200
    first = 64 + (frames + 1) * 8
    index = bytearray()
    for number in range(frames):
        index += struct.pack("<II", number, first + number * len(payload))
    index += struct.pack("<II", 0xFFFFFFFF, first + frames * len(payload))
    header = bytearray(BIF_MAGIC) + struct.pack("<III", 0, frames, 10_000)
    header += b"\x00" * (64 - len(header))
    bif = tmp_path / "film-320-10.bif"
    bif.write_bytes(bytes(header) + bytes(index) + payload * frames)
    source = tmp_path / "film.strm"
    source.write_text("http://share.invalid/x", encoding="utf-8")

    seen: list[str] = []
    sink = logger.add(lambda m: seen.append(m.record["message"]), level="DEBUG")
    try:
        inspect_preview(str(source), str(bif), runtime_s=110)
    finally:
        logger.remove(sink)

    assert not [line for line in seen if "Preview check:" in line]


def test_a_file_judged_by_its_video_stream_still_names_the_source():
    """The reason the internal line used to carry is visible in the caller's line instead."""
    from media_preview_generator.previews_audit import PreviewVerdict

    verdict = PreviewVerdict(
        problem=None,
        frames=94,
        interval_s=10,
        covered_s=940.0,
        runtime_s=941.23,
        expected_frames=95.0,
        runtime_source="video stream",
    )

    assert "(video stream)" in verdict.summary()
