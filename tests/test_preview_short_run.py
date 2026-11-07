"""A run that reads only the opening of the file must not publish a preview of it.

A cloud-drive ``.strm`` link can serve the first packets and then stop. FFmpeg decodes what it got — sometimes one
frame — and can even exit 0, so the old rule ("a CPU run that wrote frames publishes them") shipped a one-frame BIF
that looks finished. These tests pin the two guards: the frame-count share, and the belt-and-braces check for a clean
exit that read only the opening.
"""

from __future__ import annotations

import pytest

from media_preview_generator.processing.generator import (
    PUBLISH_CPU_MIN_FRAME_SHARE,
    is_a_share_of_a_run,
)


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (1, 234),  # one frame of a two-hour film: the link served its opening only
        (2, 234),
        (10, 234),
        (0, 234),
    ],
)
def test_a_few_frames_of_a_long_file_is_not_a_run(count, expected):
    assert is_a_share_of_a_run(count, expected) is False


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (234, 234),  # a complete run
        (234, 240),  # a run that lost its tail to a decoder error
        (60, 234),  # a genuinely damaged file: 25% is still a preview of it
        (-(-int(234 * PUBLISH_CPU_MIN_FRAME_SHARE * 100) // 100) + 1, 234),  # just past the boundary
    ],
)
def test_a_real_share_of_the_file_is_a_run(count, expected):
    assert is_a_share_of_a_run(count, expected) is True


def test_a_short_clip_publishes_its_few_frames():
    """A four-second clip with two thumbnails is complete, not truncated."""
    assert is_a_share_of_a_run(2, 0.4) is True
    assert is_a_share_of_a_run(1, 2) is True


def test_an_unknown_runtime_publishes_as_before():
    assert is_a_share_of_a_run(1, None) is True


def test_the_boundary_is_a_quarter():
    assert PUBLISH_CPU_MIN_FRAME_SHARE == 0.25
