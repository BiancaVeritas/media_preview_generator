"""A preview the check found wrong must be rebuilt from the source, not from the frames that made it.

The failure this pins: the job logged "Preview check: ... is wrong ...; rebuilding it in this run", then
"Frames: REUSED from cache (93 frames, no FFmpeg)", wrote the same 93 thumbnails, and reported the identical
shortfall on the next run — forever. The cache held exactly the frames that produced the truncated preview.
"""

from __future__ import annotations

import inspect

from media_preview_generator.processing import multi_server


def _source() -> str:
    return inspect.getsource(multi_server)


def _rebuild_block() -> str:
    """The stretch between the check and the frame-cache lookup."""
    source = _source()
    start = source.index("if audit_existing:")
    end = source.index("took_slow_path = False", start)
    return source[start:end]


def test_the_check_result_disables_the_frame_cache_hit():
    """``cache.get`` returns the previous run's frames; those are the ones that produced the bad preview."""
    block = _rebuild_block()

    assert "rebuilding_after_check = bool(audited_bad)" in block
    # The cache read is skipped for it, exactly as it is for an explicit regenerate.
    assert "not regenerate and not rebuilding_after_check" in block


def test_a_clean_file_still_reuses_the_cache():
    """Only a flagged preview re-extracts; every other file keeps the fast cache path."""
    block = _rebuild_block()

    assert "cached = cache.get(canonical_path, extraction_key=extraction_key)" in block
    # The lookup sits under the guard, so a file with nothing flagged still reaches it.
    guard = block.index("not regenerate and not rebuilding_after_check")
    lookup = block.index("cache.get(canonical_path")
    assert guard < lookup


def test_the_stale_cache_entry_is_dropped_after_a_flagged_rebuild():
    """Re-extraction marks the slot emptied, which is what makes ``finally`` invalidate the old entry."""
    source = _source()
    start = source.index("if not cache_hit:", source.index("took_slow_path = False"))
    block = source[start : start + 4000]

    assert "slot_emptied = use_frame_cache" in block
    # And the cleanup that makes the next run see a miss.
    assert "cache.invalidate(canonical_path)" in source
