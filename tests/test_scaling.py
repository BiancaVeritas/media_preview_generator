"""The optional thumbnail downscale algorithm."""

from __future__ import annotations

import pytest

from media_preview_generator.processing.scaling import (
    SCALER_ENV,
    cpu_scale_suffix,
    cuda_scale_suffix,
    thumbnail_scaler,
)


def test_unset_keeps_each_filter_at_its_default(monkeypatch):
    monkeypatch.delenv(SCALER_ENV, raising=False)

    assert thumbnail_scaler() is None
    assert cpu_scale_suffix() == ""
    assert cuda_scale_suffix() == ""


@pytest.mark.parametrize("value", ["lanczos", "LANCZOS", " bicubic ", "bilinear"])
def test_a_known_scaler_is_passed_to_both_filters(monkeypatch, value):
    monkeypatch.setenv(SCALER_ENV, value)

    scaler = value.strip().lower()
    assert thumbnail_scaler() == scaler
    assert cpu_scale_suffix() == f":flags={scaler}"
    assert cuda_scale_suffix() == f":interp_algo={scaler}"


@pytest.mark.parametrize("value", ["", "nearest", "area", "spline", "bogus"])
def test_unknown_values_fall_back_to_the_filter_defaults(monkeypatch, value):
    monkeypatch.setenv(SCALER_ENV, value)

    assert thumbnail_scaler() is None
    assert cpu_scale_suffix() == ""
    assert cuda_scale_suffix() == ""
