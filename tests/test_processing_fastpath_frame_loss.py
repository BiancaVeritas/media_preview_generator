"""The fast path can lose frames at the tail, and nothing caught it.

``-skip_frame:v nokey`` decodes only keyframes.  On an open-GOP encode (and on a
cloud-backed ``.strm`` whose tail never arrives) the LAST keyframe ffprobe
flags is not decodable, so the ``fps`` sampler has no frame for the final
sample points and the run quietly writes fewer thumbnails than the runtime asks
for.  Nothing else notices: the exit code is 0, no two thumbnails are identical
(so the duplicate validator stays quiet), and the drift warning's threshold is a
flat two frames — a fifth of a two-minute file.

Measured on 神秘博士 - S00E44 - 1080p.strm (98.025 s, 25 fps HEVC, interval 10 s):

    ffprobe flags 22 keyframes; the fast path decodes 21 of them, missing 88.72 s
    fast path  -> 8 thumbnails, ends at 70 s
    full decode -> 10 thumbnails, ends at 90 s

The preview was rebuilt on every run and came back 8 frames each time.
"""

from __future__ import annotations

import pytest

from media_preview_generator.processing.generator import (
    _fast_path_lost_frames,
    _warn_if_frame_count_disagrees_with_duration,
)


class TestFastPathLostFrames:
    """``_fast_path_lost_frames``: did the keyframe-only pass fall short of the runtime?"""

    def test_the_real_s00e44_shortfall_is_reported(self):
        """8 thumbnails for a 98.025 s file at a 10 s interval: expected 9.8, so 8 is short."""
        assert _fast_path_lost_frames(8, 98.025, 10) is True

    def test_a_complete_run_is_not_reported(self):
        """10 thumbnails is a complete run of the same file."""
        assert _fast_path_lost_frames(10, 98.025, 10) is False

    def test_one_frame_short_is_the_tolerated_rounding(self):
        """``fps`` may not emit the tail frame, so expected - 1 is a complete run.

        A 98.025 s file asks for 9.8.  A 9-frame run is the sampler's own
        rounding, not lost content, and must not trigger a full decode.
        """
        assert _fast_path_lost_frames(9, 98.025, 10) is False

    def test_two_frames_short_is_reported(self):
        """A 50 s file asks for 5 frames; 3 is two frames of content the run never read."""
        assert _fast_path_lost_frames(3, 50.0, 10) is True

    def test_an_unknown_runtime_reports_nothing(self):
        """No runtime means nothing says how many frames should be there."""
        assert _fast_path_lost_frames(8, None, 10) is False

    def test_a_zero_interval_reports_nothing(self):
        """Guards the division: an interval of 0 can't imply an expected count."""
        assert _fast_path_lost_frames(8, 98.025, 0) is False

    def test_a_file_shorter_than_one_interval_is_not_reported(self):
        """A 4 s clip asks for 1.4 frames; its single thumbnail is complete."""
        assert _fast_path_lost_frames(1, 4.0, 10) is False

    def test_a_long_film_losing_two_frames_is_reported(self):
        """The rule is the sampler's one frame, not a flat two: 275 -> 273 is short."""
        assert _fast_path_lost_frames(273, 2748.79, 10) is True
        assert _fast_path_lost_frames(274, 2748.79, 10) is False


class TestCutShortWarningForShortFiles:
    """The drift warning must speak up when a SHORT file loses a large share of its content."""

    def _warn(self, caplog, image_count, duration_s, interval=10):
        from types import SimpleNamespace

        media_info = SimpleNamespace(video_tracks=[SimpleNamespace(duration=duration_s * 1000)])
        config = SimpleNamespace(plex_bif_frame_interval=interval)
        _warn_if_frame_count_disagrees_with_duration("/x/Show - S01E44.mkv", "/x", image_count, media_info, config)
        return [r for r in caplog.records if r.levelname == "WARNING"]

    def test_the_real_s00e44_case_is_warned_about(self, loguru_caplog):
        """8 of 9.8 frames is a 20% shortfall on a 98 s file, and it used to be silent."""
        with loguru_caplog.at_level("WARNING"):
            warns = self._warn(loguru_caplog, 8, 98.025)
        assert warns, "8 frames for a 98 s file is 1.8 short of 9.8 — that must not pass silently"

    def test_one_frame_short_on_a_short_file_stays_quiet(self, loguru_caplog):
        """The sampler's own rounding permission still applies: 9 of 9.8 is complete."""
        with loguru_caplog.at_level("WARNING"):
            warns = self._warn(loguru_caplog, 9, 98.025)
        assert warns == []

    def test_two_frames_short_on_a_long_film_stays_quiet(self, loguru_caplog):
        """Two frames of 275 is noise the absolute slack was written for."""
        with loguru_caplog.at_level("WARNING"):
            warns = self._warn(loguru_caplog, 273, 2748.79)
        assert warns == []


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
