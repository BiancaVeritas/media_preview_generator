"""The downscale algorithm used for preview thumbnails.

The CPU path (software decode, and the final scale after a hardware download)
runs FFmpeg's ``scale`` filter, which defaults to bicubic. The GPU path runs
``scale_cuda``, whose default is bilinear — visibly soft and jagged on a 6x
downscale from 1080p to 320x180. ``THUMBNAIL_SCALER`` overrides both so a GPU
and a CPU worker produce the same character of image:

    THUMBNAIL_SCALER=lanczos   # sharper, some ringing on hard edges
    THUMBNAIL_SCALER=bicubic   # the CPU default; a good middle ground
    THUMBNAIL_SCALER=bilinear  # softest, no ringing

Unset keeps the previous behaviour exactly (CPU bicubic, CUDA bilinear), so an
existing install does not change its output on upgrade.
"""

from __future__ import annotations

import os

#: The environment variable, and the values both FFmpeg filters understand.
SCALER_ENV = "THUMBNAIL_SCALER"
SCALERS = ("bilinear", "bicubic", "lanczos")


def thumbnail_scaler() -> str | None:
    """The configured scaler, or None to leave each FFmpeg filter at its default."""
    value = os.environ.get(SCALER_ENV, "").strip().lower()
    return value if value in SCALERS else None


def cpu_scale_suffix() -> str:
    """The ``scale`` filter option for the configured scaler, ``""`` for the default."""
    scaler = thumbnail_scaler()
    return f":flags={scaler}" if scaler else ""


def cuda_scale_suffix() -> str:
    """The ``scale_cuda`` filter option for the configured scaler, ``""`` for the default."""
    scaler = thumbnail_scaler()
    return f":interp_algo={scaler}" if scaler else ""
