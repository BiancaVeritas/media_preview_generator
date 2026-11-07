"""A "异常缩略图排查" job must reach the worker that does the checking.

The option was carried from the dialog to ``Config``, but the full-scan path runs a *different* call site
(``dispatcher._run_check``, with ``check_only=True``) from the per-file generation worker, and that one never
passed the flag on. Every file with a preview was therefore reported "output already exists" during the check
stage, so the job queued nothing and finished looking like a plain missing-only run.
"""

from __future__ import annotations

import inspect

from media_preview_generator.jobs import dispatcher as dispatcher_mod
from media_preview_generator.jobs import worker as worker_mod


def _source_between(source: str, start: str, end: str) -> str:
    begin = source.index(start)
    return source[begin : source.index(end, begin)]


def test_the_dispatcher_check_stage_forwards_it():
    """``check_only=True`` is the stage that decides whether a file needs work at all."""
    source = inspect.getsource(dispatcher_mod)
    block = _source_between(source, "def _run_check", "def _run_custom_check")
    assert "check_only=True" in block, "the check stage moved; this test needs its new name"
    assert "audit_existing=" in block
    assert 'getattr(tracker.config, "audit_existing"' in block


def test_the_generation_worker_forwards_it():
    source = inspect.getsource(worker_mod)
    assert "audit_existing=" in source
    assert 'getattr(config, "audit_existing"' in source


def test_the_check_happens_before_the_already_existing_shortcut():
    """The measurement must run first: after ``all_fresh`` returns, the file never reaches it."""
    from media_preview_generator.processing import multi_server

    source = inspect.getsource(multi_server)
    audit_at = source.index("if audit_existing:")
    fresh_at = source.index("if not regenerate:", audit_at)
    assert audit_at < fresh_at, "the check must precede the 'outputs already fresh' shortcut"

    # And it deletes the bad preview, which is what makes the shortcut below fall through to generation.
    block = source[audit_at:fresh_at]
    assert "os.unlink" in block
    assert "SKIPPED_OUTPUT_EXISTS" not in block, "the check must not answer 'already done' by itself"
