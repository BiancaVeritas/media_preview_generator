"""Resolve ``.strm`` library files to the media they point at.

A ``.strm`` file is a small text file holding one URL (or one local path) to a
video that is not on this disk: Jellyfin and Emby "strm" libraries use them
for cloud drives, HTTP shares and other machines. The servers still report the
``.strm`` file as the item's path, so every external reader (FFmpeg, ffprobe,
MediaInfo) has to be handed what is *inside* the file, while outputs stay next
to the ``.strm`` file where the servers look for them.

This module is the one place that knows the difference. Call
:func:`media_input` at every boundary where a path is handed to one of those
tools; leave the ``.strm`` path itself for outputs, fingerprints and Plex's
bundle hash.

The target is read once per file state (modification time and size) and
cached, so a job's many probes don't re-read it each time.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache

STRM_SUFFIX = ".strm"
#: How many ``.strm`` files may point at another before the chain is called a loop.
MAX_STRM_DEPTH = 5

#: A URL scheme (``https://``, ``rtsp://``, ``udp://``); a Windows drive letter isn't one.
_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://")


class StrmError(OSError):
    """A ``.strm`` file that can't be resolved to the media it points at."""


@dataclass(frozen=True)
class MediaSource:
    """What a media path resolves to.

    Attributes:
        path: The path as the server reported it (the ``.strm`` file itself).
        input: What an external reader should open (the URL inside the file, or ``path``).
        is_strm: Whether ``path`` is a ``.strm`` file.
    """

    path: str
    input: str
    is_strm: bool


def is_strm(path: str | os.PathLike[str]) -> bool:
    """Whether ``path`` names a ``.strm`` file (in either case: ``.strm``, ``.STRM``)."""
    return os.fspath(path).lower().endswith(STRM_SUFFIX)


def read_strm_target(path: str | os.PathLike[str]) -> str:
    """The URL or path inside one ``.strm`` file.

    Blank lines and lines starting with ``#`` are skipped, so a file with a
    comment above its URL works. A relative path is resolved against the
    ``.strm`` file's folder, and a ``.strm`` that points at another ``.strm``
    is followed (up to :data:`MAX_STRM_DEPTH`).

    Args:
        path: The ``.strm`` file.

    Returns:
        The URL (or local path) to read.

    Raises:
        StrmError: The file is missing or unreadable, holds no target, points
            at a Kodi ``plugin://`` add-on, at a local path that doesn't exist,
            or at a chain of ``.strm`` files that never ends.
    """
    current = os.fspath(path)
    seen: set[str] = set()
    for _depth in range(MAX_STRM_DEPTH + 1):
        key = os.path.normcase(os.path.abspath(current))
        if key in seen:
            raise StrmError(f"STRM file points at itself: {path}")
        seen.add(key)
        target = _read_one(current)
        if _SCHEME_RE.match(target):
            if is_strm(target):
                raise StrmError(
                    f"STRM file points at another STRM file over the network, which can't be read: {path} -> {target}"
                )
            return target
        if not is_strm(target):
            resolved = target if os.path.isabs(target) else os.path.join(os.path.dirname(current), target)
            if not os.path.isfile(resolved):
                raise StrmError(f"STRM file points at a missing file: {path} -> {resolved}")
            return resolved
        current = target if os.path.isabs(target) else os.path.join(os.path.dirname(current), target)
    raise StrmError(f"STRM file points at more than {MAX_STRM_DEPTH} other STRM files: {path}")


def _read_one(path: str) -> str:
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as handle:
            for line in handle:
                text = line.strip().strip('"').strip()
                if not text or text.startswith("#"):
                    continue
                if text.lower().startswith("plugin://"):
                    raise StrmError(
                        f"STRM file points at a Kodi add-on, which this app can't read directly: {path} -> {text}"
                    )
                return text
    except StrmError:
        raise
    except OSError as exc:
        raise StrmError(f"STRM file couldn't be read: {path}: {exc}") from exc
    raise StrmError(f"STRM file has no URL or path inside: {path}")


@lru_cache(maxsize=4096)
def _target_for_state(path: str, _mtime_ns: int, _size: int) -> str:
    """The target of one ``.strm`` file in one state; the state is part of the key, so a rewrite is re-read."""
    return read_strm_target(path)


def _cached_target(path: str) -> str:
    try:
        info = os.stat(path)
    except OSError as exc:
        raise StrmError(f"STRM file couldn't be read: {path}: {exc}") from exc
    return _target_for_state(os.path.abspath(path), info.st_mtime_ns, info.st_size)


def resolve(path: str | os.PathLike[str]) -> MediaSource:
    """Resolve a media path to what a reader should open.

    Args:
        path: A media path as the server reported it.

    Returns:
        The source: the URL inside a ``.strm`` file, or the path itself.

    Raises:
        StrmError: The path is a ``.strm`` file that can't be resolved.
    """
    text = os.fspath(path)
    if not is_strm(text):
        return MediaSource(path=text, input=text, is_strm=False)
    return MediaSource(path=text, input=_cached_target(text), is_strm=True)


def media_input(path: str | os.PathLike[str]) -> str:
    """What FFmpeg, ffprobe, MediaInfo and the marker readers should open for ``path``.

    A ``.strm`` file gives the URL it holds; anything else is returned unchanged.
    """
    return resolve(path).input


def ffmpeg_input(path: str | os.PathLike[str], *, always_protocol: bool = False) -> str:
    """The FFmpeg ``-i`` argument for ``path``.

    Args:
        path: A media path as the server reported it.
        always_protocol: Prefix a local path with ``file:`` so a name can never
            be read as another protocol or an option (the Inspector does this).

    Returns:
        The URL for a ``.strm`` file, else the path (or ``file:<path>``).
    """
    source = resolve(path)
    if source.is_strm:
        return source.input
    return f"file:{source.input}" if always_protocol else source.input
