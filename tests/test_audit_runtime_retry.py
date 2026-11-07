"""The audit reads the .strm URL itself when no stored runtime exists, with reopen retries."""

from __future__ import annotations

from unittest.mock import patch

from media_preview_generator import previews_audit


def test_a_network_source_is_retried_when_the_first_answer_is_short(monkeypatch):
    """The first request 403s / serves the opening; a fresh connection reads the whole file."""
    monkeypatch.setattr(previews_audit, "RUNTIME_RETRY_DELAYS_S", (0, 0, 0))
    monkeypatch.setattr(
        "media_preview_generator.strm.sidecar_runtime_seconds", lambda _path: None
    )
    monkeypatch.setattr(previews_audit, "is_network_input", lambda _path: True)

    answers = iter([None, None, 7200.0])
    with patch.object(previews_audit, "_probe_runtime_once", side_effect=lambda _p: next(answers)) as probe:
        result = previews_audit._runtime_seconds("film.strm")

    assert result == 7200.0
    assert probe.call_count == 3


def test_a_good_first_answer_stops_the_retries(monkeypatch):
    """No reason to touch the share again when the first probe already read the full runtime."""
    monkeypatch.setattr(previews_audit, "RUNTIME_RETRY_DELAYS_S", (0, 0, 0))
    monkeypatch.setattr(
        "media_preview_generator.strm.sidecar_runtime_seconds", lambda _path: None
    )
    monkeypatch.setattr(previews_audit, "is_network_input", lambda _path: True)

    with patch.object(previews_audit, "_probe_runtime_once", return_value=7200.0) as probe:
        result = previews_audit._runtime_seconds("film.strm")

    assert result == 7200.0
    assert probe.call_count == 1


def test_a_bogus_short_runtime_is_not_trusted(monkeypatch):
    """A cloud link serving only the opening reports a few seconds; that must not bless a truncated preview."""
    monkeypatch.setattr(previews_audit, "RUNTIME_RETRY_DELAYS_S", (0, 0, 0))
    monkeypatch.setattr(
        "media_preview_generator.strm.sidecar_runtime_seconds", lambda _path: None
    )
    monkeypatch.setattr(previews_audit, "is_network_input", lambda _path: True)

    with patch.object(previews_audit, "_probe_runtime_once", return_value=10.0):
        assert previews_audit._runtime_seconds("film.strm") is None


def test_a_local_file_is_probed_once(monkeypatch):
    monkeypatch.setattr(previews_audit, "is_network_input", lambda _path: False)
    monkeypatch.setattr(
        "media_preview_generator.strm.sidecar_runtime_seconds", lambda _path: None
    )

    with patch.object(previews_audit, "_probe_runtime_once", return_value=1200.0) as probe:
        assert previews_audit._runtime_seconds("film.mkv") == 1200.0
    assert probe.call_count == 1


def test_the_sidecar_short_circuits_every_probe(monkeypatch):
    """With -mediainfo.json present, no network request at all."""
    monkeypatch.setattr(
        "media_preview_generator.strm.sidecar_runtime_seconds", lambda _path: 7695.712
    )

    with patch.object(previews_audit, "_probe_runtime_once", side_effect=AssertionError("probed")):
        assert previews_audit._runtime_seconds("film.strm") == 7695.712
