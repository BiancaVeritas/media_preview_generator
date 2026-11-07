"""A worker slot's displayed number restarts at 1 for a new group.

``worker_id`` is a pool-wide counter that only grows, so a group deleted and added again used to show ``#7 #8`` for its
first two slots. What the dashboard numbers is the slot's place within its group member: ``slot_number``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from media_preview_generator.jobs.dispatcher import JobDispatcher


def _worker(worker_id: int, group_id: str, member_id: str, worker_type: str = "CPU") -> MagicMock:
    worker = MagicMock()
    worker.task_ended_at = 0.0
    worker.fallback_active = False
    worker.fallback_reason = None
    worker.media_title = ""
    worker.library_name = ""
    worker.progress_percent = 0
    worker.current_job_id = None
    worker.ffmpeg_started = False
    worker.current_phase = ""
    worker.worker_id = worker_id
    worker.worker_type = worker_type
    worker.group_id = group_id
    worker.member_id = member_id
    worker.group_name = group_id
    worker.group_resource = "cpu"
    worker.node_id = None
    worker.node_name = ""
    worker.is_busy = False
    worker.current_task = None
    worker._pending_removal = False
    worker.get_progress_data.return_value = {}
    return worker


def _dispatcher_with(workers: list) -> JobDispatcher:
    dispatcher = JobDispatcher.__new__(JobDispatcher)
    pool = MagicMock()
    pool._snapshot_workers.return_value = workers
    pool._workers_lock = MagicMock()
    pool._progress_lock = MagicMock()
    pool._node_hardware = None
    dispatcher.worker_pool = pool
    return dispatcher


def test_a_recreated_group_numbers_its_slots_from_one():
    """The same two slots after a delete and re-add: high worker_ids, but numbered 1 and 2."""
    fresh = [_worker(1, "g1", "cpu"), _worker(2, "g1", "cpu")]
    recreated = [_worker(7, "g1", "cpu"), _worker(8, "g1", "cpu")]

    for workers in (fresh, recreated):
        rows = {row["worker_id"]: row["slot_number"] for row in _statuses(_dispatcher_with(workers))}
        assert sorted(rows.values()) == [1, 2]


def test_slot_numbers_are_per_member_not_per_pool():
    workers = [
        _worker(1, "g1", "cpu-a"),
        _worker(2, "g1", "cpu-b"),
        _worker(3, "g1", "cpu-a"),
    ]

    rows = {
        row["worker_id"]: row["slot_number"]
        for row in _statuses(_dispatcher_with(workers))
    }

    assert rows == {1: 1, 2: 1, 3: 2}


def test_a_retired_slot_does_not_shift_the_others():
    """Numbers follow worker_id order, so an old id keeps its place while it lives."""
    workers = [_worker(5, "g1", "cpu"), _worker(9, "g1", "cpu")]

    rows = {
        row["worker_id"]: row["slot_number"]
        for row in _statuses(_dispatcher_with(workers))
    }

    assert rows == {5: 1, 9: 2}


def _statuses(dispatcher: JobDispatcher) -> list[dict]:
    return JobDispatcher._build_worker_statuses(dispatcher)
