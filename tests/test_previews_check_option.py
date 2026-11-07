"""A Previews job's "Check existing" option.

With it, a job reads the preview already on disk and rebuilds only the file whose preview can't be right; without it the
ordinary flow is unchanged (skip a file that already has a preview). These tests pin the flag's path from the dialog to
the dispatcher, and that the audit module decides "rebuild" from the preview alone.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from media_preview_generator.bif_reader import BIF_MAGIC
from media_preview_generator.previews_audit import check_preview


def _write_bif(path: Path, frames: int, interval_ms: int = 10_000) -> Path:
    payload = b"\xff\xd8\xff\xd9"
    body = payload * frames
    first = 64 + (frames + 1) * 8
    index = bytearray()
    for number, offset in enumerate(first + index_ * len(payload) for index_ in range(frames)):
        index += struct.pack("<II", number, offset)
    index += struct.pack("<II", 0xFFFFFFFF, first + len(body))
    header = bytearray(BIF_MAGIC) + struct.pack("<III", 0, frames, interval_ms)
    header += b"\x00" * (64 - len(header))
    path.write_bytes(bytes(header) + bytes(index) + body)
    return path


@pytest.fixture
def runtime(monkeypatch):
    def set_runtime(seconds: float | None) -> None:
        monkeypatch.setattr(
            "media_preview_generator.previews_audit._runtime_seconds", lambda _path: seconds, raising=True
        )

    return set_runtime


def test_a_one_frame_preview_is_rebuilt(tmp_path, runtime):
    source = tmp_path / "film.mkv"
    source.write_bytes(b"x")
    preview = _write_bif(tmp_path / "film-320-10.bif", 1)
    runtime(7200)

    problem = check_preview(str(source), str(preview))

    assert problem is not None


def test_a_good_preview_is_left_alone(tmp_path, runtime):
    source = tmp_path / "film.mkv"
    source.write_bytes(b"x")
    preview = _write_bif(tmp_path / "film-320-10.bif", 720)
    runtime(7200)

    assert check_preview(str(source), str(preview)) is None


def test_the_option_reaches_the_pipeline_from_the_job_config(monkeypatch):
    """``config.audit_existing`` is what the worker forwards to ``process_canonical_path``."""
    from media_preview_generator.config import Config
    from media_preview_generator.jobs import worker as worker_mod

    source = Path(worker_mod.__file__).read_text(encoding="utf-8")

    assert "audit_existing" in source
    assert hasattr(Config, "__dataclass_fields__")
    assert "audit_existing" in Config.__dataclass_fields__


def test_the_flag_defaults_off():
    """The dataclass field exists and its loader default is False; reading the source keeps the test offline."""
    import inspect

    from media_preview_generator import config as config_mod

    source = inspect.getsource(config_mod.load_config)
    read = inspect.getsource(config_mod)

    assert "audit_existing" in config_mod.Config.__dataclass_fields__
    assert 'audit_existing = get_value("audit_existing", "AUDIT_EXISTING", False, bool)' in read
    assert "audit_existing=audit_existing" in read or "audit_existing=audit_existing," in read
    assert source


def test_both_previews_dialogs_offer_it():
    root = Path(__file__).resolve().parents[1] / "media_preview_generator" / "web" / "templates"

    for name in ("_start_job_modal.html", "_manual_job_modal.html"):
        page = (root / name).read_text(encoding="utf-8")
        assert 'id="jobAuditMode"' in page or 'id="manualAuditMode"' in page, name
        # A segmented Off / On control, the same one the priority row uses.
        assert "ov-seg-select" in page, name
        assert "Check for broken previews" in page, name
        assert 'data-seg-default="off"' in page, name
        assert "Check existing" not in page, name


def test_the_run_job_dialog_sends_the_flag():
    app_js = (
        Path(__file__).resolve().parents[1] / "media_preview_generator" / "web" / "static" / "js" / "app.js"
    ).read_text(encoding="utf-8")
    manual_js = (
        Path(__file__).resolve().parents[1]
        / "media_preview_generator"
        / "web"
        / "static"
        / "js"
        / "newmanual_jobs.js"
    ).read_text(encoding="utf-8")

    assert "jobConfig.audit_existing = true" in app_js
    assert "document.getElementById('jobAuditMode')?.value === 'on'" in app_js
    assert "payload.audit_existing = document.getElementById('manualAuditMode').value === 'on'" in manual_js


def test_the_option_adds_a_check_without_replacing_the_run():
    """A file with no preview is still generated; the option only also measures the ones already there."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "media_preview_generator" / "processing" / "multi_server.py"
    ).read_text(encoding="utf-8")

    start = source.index("if audit_existing:")
    block = source[start : start + 2600]
    # It records the broken preview (so this run rebuilds it) and never returns early as "already done". The old file
    # stays on disk until the rebuild succeeds: deleting first lost the preview when FFmpeg failed.
    assert "audited_bad.add" in block
    assert "os.unlink" not in block
    assert "SKIPPED_OUTPUT_EXISTS" not in block
    assert "return MultiServerResult" not in block


def test_the_audit_option_is_hidden_for_other_job_types():
    app_js = (
        Path(__file__).resolve().parents[1] / "media_preview_generator" / "web" / "static" / "js" / "app.js"
    ).read_text(encoding="utf-8")

    assert "toggle(`${prefix}AuditModeGroup`, !previews)" in app_js
