"""The job banner separates the checking sweep from the generation queue.

Checking and generation are two pools running side by side: the sweep reads each preview header (~1s per file)
and finishes the library long before the two generation workers are through the first few rebuilds. A single
"3/153 completed" made that look like the job skipped work. The banner now reports both.
"""

from __future__ import annotations

import threading
from collections import deque

from media_preview_generator.jobs.dispatcher import JobTracker


def _tracker(**overrides) -> JobTracker:
    tracker = JobTracker.__new__(JobTracker)
    tracker._counts_lock = threading.Lock()
    tracker.library_prefix = ""
    tracker.work_started = True
    tracker.generation_started = True
    tracker.node_wait = ""
    tracker.gpu_waiting = 0
    tracker.total_items = 153
    tracker.successful = 1
    tracker.failed = 0
    tracker.item_queue = deque()
    tracker.check_queue = deque()
    tracker.checked = 0
    tracker.check_flagged = 0
    tracker.handlers = None
    for key, value in overrides.items():
        setattr(tracker, key, value)
    return tracker


def test_the_sweep_progress_shows_while_generation_is_still_on_the_first_files():
    message = _tracker(checked=40, check_flagged=2).progress_message(1)

    assert "1/153 completed" in message
    assert "checked 40/153" in message
    assert "2 need rebuilding" in message


def test_a_finished_sweep_still_reports_what_it_found():
    """The count that matters once the sweep is done: how many rebuilds are left."""
    item_queue = deque([object(), object()])
    message = _tracker(checked=153, check_flagged=2, item_queue=item_queue).progress_message(1)

    assert "checked 153/153" in message
    assert "2 need rebuilding" in message


def test_nothing_flagged_keeps_the_line_short():
    """A plain missing-only job must not grow a "0 need rebuilding" tail."""
    message = _tracker(checked=153, check_flagged=0).progress_message(1)

    assert message == "1/153 completed"


def test_a_job_with_no_findings_says_nothing_extra():
    message = _tracker(checked=10, check_flagged=0).progress_message(1)

    assert "checked 10/153" in message
    assert "rebuilding" not in message


def test_nothing_counted_yet_keeps_the_plain_line():
    """Before the sweep reports anything, "checked 0/153" is noise that makes every existing message longer."""
    message = _tracker(checked=0, check_flagged=0).progress_message(1)

    assert message == "1/153 completed"


def test_the_checking_stage_reports_its_own_counter():
    """Before generation begins the banner is the sweep's, so it carries the same numbers."""
    message = _tracker(generation_started=False, checked=40, check_flagged=3).progress_message(1)

    assert "checked 40/153" in message
    assert "3 need rebuilding" in message
