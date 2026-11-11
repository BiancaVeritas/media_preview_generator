"""Find preview outputs that can't be right, without re-running every file.

A BIF's timeline is positional: frame *i* is shown at ``i * interval``. A run
that died near the start of the file (a cloud-drive link that served the
opening and nothing after it, a disk that stalled mid-read) still leaves a
valid one-frame ``.bif`` behind, and nothing about the file itself looks wrong
until the scrubber only covers the first ten seconds of a two-hour film.

This module answers "which of the previews already on disk are like that?"
from the files alone: each source's runtime (MediaInfo, or ffprobe for a
``.strm`` link) against the frames its preview holds. It never decodes a video,
so checking a whole library costs one stat and one header read per file.

Used by the ``previews-audit`` job (Run a job → Previews → Check previews),
which regenerates only the files this reports.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from .bif_reader import read_bif_metadata
from .strm import StrmError, is_network_input, media_input

#: A cloud-backed .strm's HTTP link often answers the first probe with a 403 or just the opening. The generation
#: pipeline already reopens it (0s, 2s, 8s) and reads the whole file on the second try; the audit's one-shot probe
#: used to give up and silently call an obviously truncated preview healthy. Mirror those delays here.
RUNTIME_RETRY_DELAYS_S: tuple[int, ...] = (0, 2, 8)

#: A preview must hold this share of the frames its runtime asks for to count as healthy.
#:
#: ``0.95`` is the generator's own rule (``PUBLISH_MIN_FRAME_RATIO``): a complete run lands within a frame or two of
#: 100%, and anything a decoder dropped at the tail keeps it above 95%. Below that, the run stopped part-way — the
#: failure this audit exists to find. At a 10 s interval it allows a preview to end 2 minutes early on a 40-minute file,
#: 6 on a two-hour one, and 9 on a three-hour one: already far past anything a good run leaves behind.
#:
#: The share on its own is unusable for a short file, though: a 2-minute clip asks for 9.6 frames, so one frame of
#: rounding is already 90% and a perfectly good preview fails. :data:`MIN_FRAME_SLACK` covers that end of the range.
MIN_HEALTHY_FRAME_SHARE = 0.95
#: Frames a preview may fall short of its runtime no matter how short the file is.
#:
#: ``fps=1/10`` emits at 0, 10, 20 … and whether the last one lands before the end is a coin flip, so a complete run
#: is routinely one frame below ``runtime / interval``. For a 2-minute file that one frame is 10% — twice the 5% share —
#: while for a feature film it is noise the share already absorbs. Exactly ONE, not more: two frames missing is a
#: second of content that the run failed to read, and on a short clip it is also the difference between "rounding" and
#: "a tenth of the preview is gone".
MIN_FRAME_SLACK = 1
#: A preview that ends this many minutes before the runtime is also reported, whatever its share. A stated runtime can
#: run past its video stream, and a preview's last frame sits up to one thumbnail interval early, so a couple of minutes
#: is normal; a quarter of an hour is not. This catches a stop part-way on a long film that 95% alone would let through
#: (95% of a three-hour file still hides 9 minutes).
SHORTFALL_TOLERANCE_S = 300
#: A preview holding more than this share of the frames its runtime asks for is wrong too: a writer that can't read the
#: runtime (an older FFmpeg, a container whose index it can't parse) falls back to a frame every second or every tick,
#: filling the BIF with the same picture and growing it past a gigabyte for a film. Nothing a healthy run writes comes
#: near this: the frames sit at one per interval, so 100% is the ceiling and a tail lost to a decoder only lowers it.
MAX_HEALTHY_FRAME_SHARE = 1.5
#: A runtime shorter than this from a NETWORK probe is treated as a failed read and retried: a cloud share that serves
#: just the opening reports a few seconds. Used only for deciding whether to probe again — never for judging a preview.
#: Real clips shorter than a minute are legitimate and are judged by their frames like any other file.
MIN_AUDIT_DURATION_S = 60
#: How much longer the audio may run past the video before the tail is treated as audio-only (an ED/outro playing over
#: a still or a fade). Under this, video and audio end together as usual, so a short preview really is short.
#:
#: Measured on real files: an intact file's two streams end within 0.1 s of each other, and so do both streams of a
#: truncated one (an interrupted copy cuts them together) — while the audio-only tails in a real library ran 43 s, 109 s,
#: 218 s and 358 s past the picture. Anything from ~10 s upward separates the two populations, so 30 s leaves a wide
#: margin on both sides rather than sitting near either.
AUDIO_ONLY_TAIL_MIN_S = 30

#: How long ffprobe may take to read each stream's last packet when deciding why a preview is short.
STREAM_END_PROBE_TIMEOUT_S = 120


@dataclass(frozen=True)
class PreviewProblem:
    """One output that can't be the preview of its source.

    Attributes:
        media_path: The library file (or ``.strm`` file) the preview belongs to.
        preview_path: The ``.bif`` that is wrong.
        reason: Why it can't be right, in the words the UI shows.
        frames: Frames the preview holds.
        expected_frames: Frames a complete preview of the file would hold, or None when its runtime is unknown.
    """

    media_path: str
    preview_path: str
    reason: str
    frames: int
    expected_frames: float | None


@dataclass(frozen=True)
class PreviewVerdict:
    """What one check measured, whether or not the preview passed.

    ``check_preview`` returns only the problem (or None), which is all a caller deciding what to rebuild needs. That
    loses the numbers on the way out, so the job log could not show why a preview was accepted. This carries them.

    Attributes:
        problem: Why the preview can't be right, or None when it passed.
        frames: Frames the preview holds.
        interval_s: Seconds between the preview's frames.
        covered_s: How much of the video those frames cover (``frames * interval_s``).
        runtime_s: The runtime the verdict was judged against.
        expected_frames: Frames a complete run of that runtime writes.
        runtime_source: Where ``runtime_s`` came from ("record", "video stream", or "unknown").
    """

    problem: PreviewProblem | None
    frames: int
    interval_s: int
    covered_s: float
    runtime_s: float | None
    expected_frames: float | None
    runtime_source: str

    @property
    def passed(self) -> bool:
        return self.problem is None

    def summary(self) -> str:
        """One line with every number the decision used, for the job log.

        Duration is printed as ``m:ss`` so a 23-second clip does not read as "0.4 min", and the difference is signed:
        a complete preview sits at or one frame above the expected count (``fps=1/10`` may emit the frame at the very
        end), which ``-0``/``+1`` shows at a glance.
        """
        if self.runtime_s is None:
            return f"{self.frames} frames covering {_clock(self.covered_s)}, no runtime readable"
        expected = self.expected_frames or 0.0
        diff = self.frames - expected
        return (
            f"{self.frames} frames covering {_clock(self.covered_s)} vs {expected:.0f} expected "
            f"for {_clock(self.runtime_s)} of video ({self.runtime_source}); {diff:+.0f} frames"
        )


def _clock(seconds: float) -> str:
    """``1:23.4`` for a number of seconds, so short clips read naturally in a log line."""
    minutes, rest = divmod(max(0.0, float(seconds)), 60.0)
    return f"{int(minutes)}:{rest:04.1f}"


def _probe_runtime_once(media_path: str) -> float | None:
    """One attempt at reading the runtime; None when this answer is unusable."""
    from .processing.generator import read_media_info

    try:
        info = read_media_info(media_path, parse_speed=0.5)
    except (OSError, RuntimeError):
        return None
    duration_ms = float(getattr(info.video_tracks[0], "duration", 0) or 0) if info.video_tracks else 0.0
    return duration_ms / 1000.0 if duration_ms > 0 else None


def _runtime_seconds(media_path: str) -> float | None:
    """The source's runtime in seconds, or None when it can't be read.

    Order deliberately avoids hammering the cloud link:

    1. ``<name>-mediainfo.json`` beside a .strm (StrmAssistant probed it once and saved the answer) — zero network.
    2. Otherwise probe the source ourselves. A network source gets the same reopen-on-short-answer retries as the
       generation pipeline: the first request can 403 or serve only the header, and a fresh connection a moment later
       reads the whole file. A duration that still comes back implausibly short is treated as a failed probe, not as
       the truth — blessing a one-frame preview beside a ten-second "runtime" was how truncated previews slipped
       through.
    """
    from .strm import sidecar_runtime_seconds

    sidecar = sidecar_runtime_seconds(media_path)
    if sidecar is not None and sidecar > 0:
        return sidecar

    first = _probe_runtime_once(media_path)
    if not is_network_input(media_path):
        return first
    best = first
    for delay in RUNTIME_RETRY_DELAYS_S[1:]:
        if best is not None and best >= MIN_AUDIT_DURATION_S:
            break
        time.sleep(delay)
        attempt = _probe_runtime_once(media_path)
        if attempt is not None and (best is None or attempt > best):
            best = attempt
    # A few seconds from a cloud link is the opening, not the film; never let it stand in for the runtime.
    if best is not None and best < MIN_AUDIT_DURATION_S:
        return None
    return best


def _expected_frames(runtime_s: float | None, interval_s: int) -> float | None:
    """Frames a complete run over ``runtime_s`` writes: ``floor(runtime / interval) + 1``.

    Not rounded, and the ``+ 1`` is the frame at offset 0. The generator samples at 0, 10, 20 … while the playhead is
    inside the file, so a 96-second clip yields 9 frames (0, 10, …, 80) and a 2748.79-second film yields 275
    (0 … 2740). ``round(2748.79 / 10)`` happens to give 275 too, but ``round(96 / 10) = 10`` asks for a frame that
    cannot exist, failing a complete preview of a short clip — which is exactly what this function must not do.
    """
    if not runtime_s or interval_s <= 0:
        return None
    return float(int(runtime_s / interval_s) + 1)


def _covers_its_run(frames: int, expected: float | None) -> bool:
    """Whether ``frames`` is what a complete run over ``expected`` frames looks like.

    A preview passes when it is within EITHER of two tolerances — whichever is more forgiving for its length:

    * ``MIN_FRAME_SLACK`` frames. This is what a short file needs: a 2-minute clip asks for 10 frames, so one frame of
      ``fps=1/10`` rounding is a tenth of the whole preview and any percentage rule fails a perfect run.
    * 5% of the expected count. This is what a film needs: one frame out of 275 is noise, but a run that stopped 20
      frames short is 7% and really did miss content.

    Taking the more forgiving of the two keeps both ends honest: a short clip is not failed over rounding, and a film
    is not passed after dropping a chunk. Only the ONE frame the generator may not emit is excused by the absolute
    rule (``expected - 1``), never more.

    Args:
        frames: Frames the preview holds.
        expected: Frames a complete run would write, or None when the runtime is unknown.

    Returns:
        True when the count is complete enough to publish.
    """
    if expected is None or expected <= 0:
        return True
    by_slack = expected - MIN_FRAME_SLACK
    by_share = expected * MIN_HEALTHY_FRAME_SHARE
    return frames >= min(by_slack, by_share)


def _probe_video_end(media_path: str) -> float | None:
    """Where the PICTURE really stops, in seconds; None when the file can't be read.

    Only the video stream matters here: a preview is made from pictures, so the video stream's last timestamp is the
    only length that can say how many thumbnails a complete run yields. The container's duration counts the sound too
    and is therefore no use for this — an outro or ED over a fade, or a runtime record left by an older copy of the
    file, both make it longer than the picture.

    ``-select_streams v:0`` keeps ffprobe to that one stream. Over a ``.strm`` cloud link the read is one HTTP request
    either way, but limiting the stream means less of it is demuxed and parsed.
    """
    try:
        source = media_input(media_path)
    except StrmError:
        # An unreachable .strm has nothing to measure; the caller falls back to reporting the preview as short.
        return None
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "packet=pts_time",
        "-of",
        "csv=p=0",
        source,
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=STREAM_END_PROBE_TIMEOUT_S, check=False
        )
    except (subprocess.SubprocessError, OSError):
        return None
    if proc.returncode != 0:
        return None
    last: float | None = None
    for line in proc.stdout.splitlines():
        text = line.strip()
        if not text or text == "N/A":
            continue
        try:
            pts = float(text.split(",")[-1])
        except ValueError:
            continue
        if last is None or pts > last:
            last = pts
    return last


def _interval_from_name(preview: Path, default: int) -> int:
    """The thumbnail interval a ``<name>-<width>-<interval>.bif`` sidecar says it was written at."""
    try:
        parts = preview.stem.rsplit("-", 2)
        return int(parts[2]) if len(parts) == 3 and parts[2].isdigit() else default
    except (IndexError, ValueError):
        return default


def check_preview(
    media_path: str,
    preview_path: str,
    *,
    default_interval_s: int = 10,
    runtime_s: float | None = None,
) -> PreviewProblem | None:
    """Whether one preview can be the preview of its source.

    Args:
        media_path: The library file the preview belongs to.
        preview_path: The ``.bif`` to check.
        default_interval_s: The thumbnail interval to assume when the file name doesn't state one.
        runtime_s: An optional runtime the caller already knows (the media server's own record). When it is given, the
            source is NOT probed — that avoids a network request to the cloud link. Without one, the source is read
            ourselves: first ``<name>-mediainfo.json`` if it exists, else the real URL with retries. No repeated
            probing of a share just because a metadata file was already there.

    Returns:
        The problem, or None when the preview holds a plausible number of frames.
    """
    verdict = inspect_preview(
        media_path,
        preview_path,
        default_interval_s=default_interval_s,
        runtime_s=runtime_s,
    )
    return verdict.problem


#: Bytes a BIF's header occupies; the index table and the JPEG payload follow it. Mirrors ``bif_reader._HEADER_SIZE``.
_BIF_HEADER_SIZE = 64


def _structure_problem(metadata) -> str | None:
    """Whether the BIF's own byte layout is broken, in the words the UI shows; None when it holds together.

    The index table lists, per frame, where its JPEG starts; those offsets must land inside the file. A run that died
    mid-write (disk full, killed, a cloud link that dropped) can leave a complete index over half a payload, and the
    frame COUNT then looks perfect — every count-based rule passes while the last thumbnails cannot be read at all.

    Costs nothing beyond what :func:`read_bif_metadata` already parsed: no extra read, no network.
    """
    size = metadata.file_size
    offsets = metadata.frame_offsets
    if any(offset >= size for offset in offsets):
        beyond = sum(1 for offset in offsets if offset >= size)
        return (
            f"预览文件不完整：{beyond} 张缩略图的数据位置超出文件末尾（文件仅 {size / 1024:.0f} KB），"
            f"写入可能被中断"
        )
    if any(offset < _BIF_HEADER_SIZE for offset in offsets):
        return f"预览文件索引损坏：有缩略图位置落在文件头部（{size / 1024:.0f} KB）"
    if any(frame_size <= 0 for frame_size in metadata.frame_sizes):
        bad = sum(1 for frame_size in metadata.frame_sizes if frame_size <= 0)
        return f"预览文件索引错乱：{bad} 张缩略图的大小非正常值（可能被截断或写入中断）"
    last_end = offsets[-1] + metadata.frame_sizes[-1] if offsets else 0
    if last_end > size:
        return f"预览文件末尾被截断：最后一张缩略图越出文件末尾 {last_end - size} 字节"
    return None


def inspect_preview(
    media_path: str,
    preview_path: str,
    *,
    default_interval_s: int = 10,
    runtime_s: float | None = None,
) -> PreviewVerdict:
    """Measure one preview against its source and report every number the decision used.

    ``check_preview`` answers "is this wrong?"; this answers "what did we see?", so the job log can print the runtime,
    the frame count it implies, the frames actually present and the difference between them — including for a preview
    that passed. A passing preview is otherwise indistinguishable from one that was never looked at.

    Args:
        media_path: The library file the preview belongs to.
        preview_path: The ``.bif`` to check.
        default_interval_s: The thumbnail interval to assume when the file name doesn't state one.
        runtime_s: A runtime the caller already knows; see :func:`check_preview`.

    Returns:
        The verdict: the problem (or None) plus the measurements behind it.
    """
    preview = Path(preview_path)
    try:
        metadata = read_bif_metadata(str(preview))
    except (OSError, ValueError) as exc:
        return PreviewVerdict(
            problem=PreviewProblem(
                media_path=media_path,
                preview_path=preview_path,
                reason=f"预览文件无法读取：{exc}",
                frames=0,
                expected_frames=None,
            ),
            frames=0,
            interval_s=max(1, default_interval_s),
            covered_s=0.0,
            runtime_s=None,
            expected_frames=None,
            runtime_source="unknown",
        )
    if metadata.frame_count <= 0:
        return PreviewVerdict(
            problem=PreviewProblem(
                media_path=media_path,
                preview_path=preview_path,
                reason="预览文件是空的（0 帧）",
                frames=0,
                expected_frames=None,
            ),
            frames=0,
            interval_s=max(1, default_interval_s),
            covered_s=0.0,
            runtime_s=None,
            expected_frames=None,
            runtime_source="unknown",
        )

    interval_s = max(1, round((metadata.frame_interval_ms or default_interval_s * 1000) / 1000))
    covered_s = metadata.frame_count * interval_s
    frames = metadata.frame_count

    def verdict(problem: PreviewProblem | None, judged_runtime: float | None, source: str) -> PreviewVerdict:
        return PreviewVerdict(
            problem=problem,
            frames=frames,
            interval_s=interval_s,
            covered_s=covered_s,
            runtime_s=judged_runtime,
            expected_frames=_expected_frames(judged_runtime, interval_s),
            runtime_source=source,
        )

    # The file's own byte layout comes first: an index that points past the end of the file means some thumbnails
    # cannot be read at all, and comparing frame counts over that would pass a preview the scrubber can't draw. This
    # costs nothing (the index is already parsed) and no runtime is needed, so it answers before any probing.
    structure = _structure_problem(metadata)
    if structure is not None:
        return verdict(
            PreviewProblem(
                media_path=media_path,
                preview_path=preview_path,
                reason=structure,
                frames=frames,
                expected_frames=None,
            ),
            None,
            "unknown",
        )

    # A known runtime (the media server's own record, or the <name>-mediainfo.json StrmAssistant already wrote) wins:
    # it costs no network request, so a cloud share is never probed repeatedly. Only when there is no known runtime do
    # we read the real .strm URL ourselves — with retries, since that link is what can 403 or serve just the opening.
    from_record = runtime_s is not None and runtime_s > 0
    if not from_record:
        runtime_s = _runtime_seconds(media_path)
    source = "record" if from_record else "probe"
    expected = _expected_frames(runtime_s, interval_s)
    if expected is None or runtime_s is None:
        # No runtime from the record or ffprobe. Rather than guessing from the frame count (a real 7-second clip and a
        # truncated read of a 2-hour film both have one frame), measure the video stream itself. A short clip's few
        # frames then match its short video; a long video's do not. Only if the video can't be read at all do we fall
        # back to reporting a preview that covers just the opening.
        video_end = _probe_video_end(media_path)
        video_expected = _expected_frames(video_end, interval_s) if video_end is not None else None
        if video_expected is not None and _covers_its_run(frames, video_expected):
            return verdict(None, video_end, "video stream")
        return verdict(
            PreviewProblem(
                media_path=media_path,
                preview_path=preview_path,
                reason=(
                    f"只有 {frames} 张缩略图（覆盖约 {covered_s / 60:.0f} 分钟），"
                    f"且读不到视频时长（网络源可能拒绝访问）；预览图只覆盖了开头，无法对应正常长度的视频"
                ),
                frames=frames,
                expected_frames=None,
            ),
            video_end,
            "video stream" if video_end is not None else "unknown",
        )

    shortfall_s = runtime_s - covered_s
    share = frames / expected
    if share > MAX_HEALTHY_FRAME_SHARE:
        # The BIF says its frames are one interval apart, but it holds far more of them than the file has intervals: it
        # was written by something that didn't know the runtime (every frame the same picture, at a fraction of the
        # stated interval) or at a different interval than its name claims.
        return verdict(
            PreviewProblem(
                media_path=media_path,
                preview_path=preview_path,
                reason=(
                    f"缩略图数量异常：{frames} 张（{metadata.file_size / 1024 / 1024:.0f} MB），"
                    f"约为视频时长 {runtime_s / 60:.0f} 分钟所需 {expected:.0f} 张的 {share:.0%}，"
                    f"超出正常范围（可能是旧版 FFmpeg 读不到时长，一直重复同一张图）"
                ),
                frames=frames,
                expected_frames=expected,
            ),
            runtime_s,
            source,
        )
    if _covers_its_run(frames, expected) and shortfall_s <= SHORTFALL_TOLERANCE_S:
        return verdict(None, runtime_s, source)
    # Short by the recorded runtime — but that figure describes the CONTAINER (sound included), while thumbnails are
    # made from the VIDEO. Two everyday things make the container longer than the picture, and neither is a fault:
    # an outro or ED over a fade, and a runtime record left behind by an older copy of the file. So before calling this
    # a failed run, ask the only question that matters: how many frames can the file's video actually yield? One
    # ffprobe read of the video stream answers it, and only a preview that already looks short pays for it.
    #
    # Nothing is logged here: the caller prints one line per file, and it names this reason through the verdict's
    # runtime source ("video stream"). An extra line with the same "Preview check:" prefix read as a second file.
    video_end = _probe_video_end(media_path)
    if video_end is not None:
        video_expected = _expected_frames(video_end, interval_s)
        if _covers_its_run(frames, video_expected) and video_end - covered_s <= SHORTFALL_TOLERANCE_S:
            return verdict(None, video_end, "video stream")
    return verdict(
        PreviewProblem(
            media_path=media_path,
            preview_path=preview_path,
            reason=(
                f"只有 {frames} 张缩略图（约 {covered_s / 60:.0f} 分钟），"
                f"而视频时长 {runtime_s / 60:.0f} 分钟，应有约 {expected:.0f} 张"
                f"，缺 {shortfall_s / 60:.0f} 分钟"
            ),
            frames=frames,
            expected_frames=expected,
        ),
        runtime_s,
        source,
    )


def _media_for_sidecar(preview: Path) -> Path | None:
    """The media file a ``<name>-<width>-<interval>.bif`` sidecar sits beside, when it is there."""
    stem = preview.stem
    parts = stem.rsplit("-", 2)
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        return None
    base = parts[0]
    for suffix in (".strm", ".mp4", ".mkv", ".m4v", ".mov", ".avi", ".ts", ".m2ts", ".wmv", ".webm", ".mpg", ".mpeg"):
        candidate = preview.with_name(base + suffix)
        if candidate.is_file():
            return candidate
    return None


def scan_folder(folder: str, *, default_interval_s: int = 10, max_files: int | None = None) -> list[PreviewProblem]:
    """Check every Emby-style ``.bif`` sidecar under ``folder``.

    Args:
        folder: The library folder to walk.
        default_interval_s: The thumbnail interval to assume when a file name doesn't state one.
        max_files: Stop after this many sidecars (a first pass on a huge library).

    Returns:
        One entry per preview that can't be right, in the order they were found.
    """
    problems: list[PreviewProblem] = []
    checked = 0
    for root, _dirs, files in os.walk(folder):
        for name in files:
            if not name.lower().endswith(".bif"):
                continue
            preview = Path(root) / name
            media = _media_for_sidecar(preview)
            if media is None:
                continue
            checked += 1
            try:
                problem = check_preview(str(media), str(preview), default_interval_s=default_interval_s)
            except StrmError as exc:
                logger.debug("Skipping {}: {}", preview, exc)
                continue
            if problem is not None:
                problems.append(problem)
            if max_files is not None and checked >= max_files:
                logger.info("Preview audit stopped after {} sidecars (limit reached)", checked)
                return problems
    logger.info("Preview audit checked {} sidecar(s); {} look wrong", checked, len(problems))
    return problems


def describe_media(path: str) -> str:
    """The URL or path a preview was made from, for the audit's report."""
    try:
        return media_input(path)
    except StrmError:
        return path


def _main(argv: list[str] | None = None) -> int:
    """``python -m media_preview_generator.previews_audit --path /media``: report (or delete) bad previews."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="python -m media_preview_generator.previews_audit",
        description="Find preview .bif files whose frame count can't cover their video's runtime.",
    )
    parser.add_argument("--path", required=True, help="Library folder to scan.")
    parser.add_argument("--interval", type=int, default=10, help="Thumbnail interval in seconds (default 10).")
    parser.add_argument("--max-files", type=int, default=None, help="Stop after this many sidecars.")
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Delete each broken .bif (and its .meta) so the next scan regenerates only those files.",
    )
    parser.add_argument("--json", action="store_true", help="Print the findings as JSON.")
    args = parser.parse_args(argv)

    problems = scan_folder(args.path, default_interval_s=args.interval, max_files=args.max_files)
    if args.json:
        import json

        print(
            json.dumps(
                [
                    {
                        "media": p.media_path,
                        "preview": p.preview_path,
                        "frames": p.frames,
                        "expected": p.expected_frames,
                        "reason": p.reason,
                    }
                    for p in problems
                ],
                ensure_ascii=False,
                indent=1,
            )
        )
    else:
        for problem in problems:
            print(f"{problem.preview_path}\n  {problem.reason}")
        print(f"\n{len(problems)} preview(s) look wrong.")

    if args.fix and problems:
        removed = 0
        for problem in problems:
            preview = Path(problem.preview_path)
            for target in (preview, preview.with_suffix(preview.suffix + ".meta")):
                try:
                    target.unlink()
                    removed += 1
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    print(f"could not delete {target}: {exc}", file=sys.stderr)
        print(f"Deleted {removed} file(s); the next scan regenerates only those.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
