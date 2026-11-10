"""The preview audit logs every verdict, not only the findings.

A whole-library sweep prints one line per file. That is deliberate: this job exists to answer "did the check run, and
what did it see", and a log that only ever shows failures cannot tell a clean sweep from one that never happened.
"""

from __future__ import annotations

import inspect


def _sweep_block() -> str:
    from media_preview_generator.processing import multi_server

    source = inspect.getsource(multi_server)
    start = source.index("if audit_existing:")
    return source[start : start + 4000]


def test_a_sound_verdict_is_logged_at_info():
    """Visible at the default INFO level — no environment variable, no extra setting."""
    block = _sweep_block()

    assert '"Preview check: {} is sound' in block
    # The call that writes it is a plain info, not a level switch or a debug.
    sound = block[block.index("elif broken == 0:") : block.index("else:", block.index("elif broken == 0:"))]
    assert "logger.info(" in sound
    assert "logger.debug(" not in sound
    assert "audit_verbose" not in sound


def test_a_file_with_no_preview_is_logged_too():
    block = _sweep_block()
    head = block[: block.index("elif broken == 0:")]
    assert "has no preview yet" in head and "logger.info(" in head


def test_findings_are_logged_at_info():
    block = _sweep_block()
    assert '"Preview check: {} is wrong' in block


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
    # The wording spans a line break in the source; check both halves.
    assert "verdict is logged" in source
    assert "rebuilt in this run" in source
