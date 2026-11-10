"""The preview audit's log output: always say what it found, and optionally every verdict.

A whole-library sweep that printed one line per healthy file would bury the findings, so by default each file's
"sound" verdict is DEBUG and only findings are INFO. Setting PREVIEW_AUDIT_VERBOSE shows every verdict instead.
"""

from __future__ import annotations

import pytest

from media_preview_generator.processing import multi_server


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("PREVIEW_AUDIT_VERBOSE", raising=False)


def test_verbose_is_off_by_default():
    assert multi_server.audit_verbose() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " 1 "])
def test_verbose_accepts_the_usual_spellings(monkeypatch, value):
    monkeypatch.setenv("PREVIEW_AUDIT_VERBOSE", value)
    assert multi_server.audit_verbose() is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "anything"])
def test_verbose_is_off_for_anything_else(monkeypatch, value):
    monkeypatch.setenv("PREVIEW_AUDIT_VERBOSE", value)
    assert multi_server.audit_verbose() is False


def test_findings_are_logged_at_info():
    """A flagged preview must always reach the job log, whatever the verbosity."""
    import inspect

    source = inspect.getsource(multi_server)
    start = source.index("if audit_existing:")
    block = source[start : start + 4000]

    assert 'logger.info(\n                    "Preview check: {} is wrong' in block
    assert '"INFO" if audit_verbose() else "DEBUG"' in block


def test_the_sweep_announces_itself():
    """The job log should say a preview audit started and how to see every verdict."""
    import inspect

    from media_preview_generator.jobs import dispatcher

    source = inspect.getsource(dispatcher)
    assert "Preview check enabled:" in source
    assert "PREVIEW_AUDIT_VERBOSE" in source
