"""The job log's worker label and the dashboard's #N must be the same number.

They came from two counters: the dashboard numbered slots inside their group, while the log printed
``worker.worker_id + 1`` — a pool-wide counter that only grows. A group deleted and re-added therefore logged
"CPU 工作进程 · 3/4" while the same two slots showed #1/#2 on screen.
"""

from __future__ import annotations

from media_preview_generator.jobs.worker import Worker, _group_display_name


def _worker(worker_id: int, slot_number: int | None = None) -> Worker:
    worker = Worker(worker_id, "CPU")
    if slot_number is not None:
        worker.slot_number = slot_number
    return worker


def test_the_log_label_uses_the_slot_number_not_the_pool_counter():
    """worker_id 11 in the first slot of a two-slot group: the log must say 1, not 12."""
    worker = _worker(11, slot_number=1)

    assert _group_display_name("CPU 工作进程", worker) == "CPU 工作进程 · 1"


def test_a_recreated_group_logs_one_and_two_again():
    recreated = [_worker(11, slot_number=1), _worker(12, slot_number=2)]

    labels = [_group_display_name("CPU 工作进程", w) for w in recreated]

    assert labels == ["CPU 工作进程 · 1", "CPU 工作进程 · 2"]


def test_a_node_worker_is_named_by_its_device():
    """A node worker's own lines carry the node/device prefix, so that wins over any number."""
    worker = Worker(5, "CPU", node_id="n1", node_name="lab-gpu")
    worker.slot_number = 2

    assert _group_display_name("Lab nodes", worker) == "Lab nodes · lab-gpu/CPU"


def test_a_fresh_worker_defaults_to_a_sane_number():
    """Before the pool stamps it, the label is still readable (never "· None")."""
    worker = _worker(0)

    assert _group_display_name("CPU 工作进程", worker) == "CPU 工作进程 · 1"
