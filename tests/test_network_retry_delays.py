"""How long the pipeline waits before re-opening a stalled network stream.

The waits were 0/2/8 s, which all fall inside one throttling window: none of them could ever succeed, and re-asking
at once is exactly what trips a cloud share's rate limiting. They are now long enough to cross a window, and
overridable so a user can restore the old pacing.
"""

from __future__ import annotations

import pytest

from media_preview_generator.processing import generator


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv(generator._RETRY_DELAYS_ENV, raising=False)


def test_the_default_crosses_a_throttling_window():
    """A share throttles for minutes; a few seconds of retries can never get past it."""
    delays = generator._network_retry_delays()

    assert delays == generator.NETWORK_INPUT_RETRY_DELAYS_S
    assert min(delays) >= 15, "the first retry must give the share time to recover"
    assert sum(delays) >= 120, "the total must span a typical throttling window"


def test_the_old_pacing_can_be_restored(monkeypatch):
    monkeypatch.setenv(generator._RETRY_DELAYS_ENV, "0,2,8")

    assert generator._network_retry_delays() == (0, 2, 8)


def test_a_custom_list_is_honoured(monkeypatch):
    monkeypatch.setenv(generator._RETRY_DELAYS_ENV, "5, 10, 20")

    assert generator._network_retry_delays() == (5, 10, 20)


@pytest.mark.parametrize("bad", ["garbage", "-5", "10,abc", "", "  "])
def test_a_bad_value_falls_back_to_the_default(monkeypatch, bad):
    """A typo in a compose file must never stop previews from being generated."""
    monkeypatch.setenv(generator._RETRY_DELAYS_ENV, bad)

    assert generator._network_retry_delays() == generator.NETWORK_INPUT_RETRY_DELAYS_S


def test_trailing_commas_are_tolerated(monkeypatch):
    """``1,,2`` is a slip, not a mistake worth rejecting: the empty field is simply skipped."""
    monkeypatch.setenv(generator._RETRY_DELAYS_ENV, "1,,2")

    assert generator._network_retry_delays() == (1, 2)
