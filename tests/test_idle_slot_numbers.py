"""The idle-worker list the dashboard shows before any job runs must number CPU slots from 1."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from media_preview_generator.web.routes.api_jobs import _build_idle_workers_from_config


def _settings(monkeypatch, *, groups, cpu_threads=2):
    settings = MagicMock()
    settings.worker_groups = groups
    settings.cpu_threads = cpu_threads
    settings.gpu_config = []
    monkeypatch.setattr(
        "media_preview_generator.web.settings_manager.get_settings_manager", lambda: settings
    )


def test_legacy_cpu_slots_start_at_one(monkeypatch):
    """No worker_groups configured: the plain cpu_threads fallback used to omit slot_number entirely.

    The dashboard then fell back to ordering by worker_id, a pool-wide counter, so a single CPU group showed "#2 #3"
    once any earlier slots had been created.
    """
    _settings(monkeypatch, groups=None)
    with patch(
        "media_preview_generator.web.routes.api_jobs._ensure_gpu_cache", return_value=[]
    ):
        rows = [r for r in _build_idle_workers_from_config() if r["worker_type"] == "CPU"]

    assert [r["slot_number"] for r in rows] == [1, 2]


def test_legacy_gpu_slots_start_at_one(monkeypatch):
    _settings(monkeypatch, groups=None, cpu_threads=0)
    with patch(
        "media_preview_generator.web.routes.api_jobs._ensure_gpu_cache",
        return_value=[{"device": "0", "type": "NVIDIA", "name": "GPU", "status": "ok"}],
    ):
        rows = [r for r in _build_idle_workers_from_config() if r["worker_type"] == "GPU"]

    assert [r["slot_number"] for r in rows] == [1]
