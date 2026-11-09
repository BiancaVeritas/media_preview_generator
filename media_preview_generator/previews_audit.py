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
#: Files this short have so few thumbnails that the share can't tell a good preview from a bad one, so they are skipped.
MIN_AUDIT_DURATION_S = 60
#: With no usable runtime, a preview covering less than this cannot be the preview of any real video. At a 10 s
#: interval that is ~15 minutes (90 frames): well below a feature film, an episode, or a normal clip, but far above
#: the 1–7 frames a run that died after the opening leaves behind. Guards the case where a .strm HTTP source returns
#: 403 (no runtime at all) or serves just the header (ffprobe reports a few seconds).
MIN_PLAUSIBLE_COVERAGE_S = 900
#: How much longer the audio may run past the video before the tail is treated as audio-only (an ED/outro playing over
#: a still or a fade). Under this, video and audio end together as usual, so a short preview really is short.
AUDIO_ONLY_TAIL_MIN_S = 60

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
    if not runtime_s or interval_s <= 0:
        return None
    return runtime_s / interval_s


def _covers_its_run(frames: int, expected: float | None) -> bool:
    """Whether ``frames`` is what a complete run over ``expected`` frames looks like.

    Two rules, either of which passes:

    * within 5% of the expected count — the generator's own completeness rule, right for a film;
    * within ``MIN_FRAME_SLACK`` frames of it — the same rule expressed absolutely, for a short file where one frame of
      ``fps=1/10`` rounding is a tenth of the whole preview. A 2-minute clip asks for 9.6 frames and a good run writes
      9 or 10; judging that by the share alone fails a perfect preview.

    Args:
        frames: Frames the preview holds.
        expected: Frames a complete run would write, or None when the runtime is unknown.

    Returns:
        True when the count is complete enough to publish.
    """
    if expected is None or expected <= 0:
        return True
    if frames >= expected - MIN_FRAME_SLACK:
        return True
    return frames / expected >= MIN_HEALTHY_FRAME_SHARE


@dataclass(frozen=True)
class _StreamEnds:
    """Where a file's streams really stop, from one ffprobe pass.

    Attributes:
        video_end: Seconds to the last video packet.
        audio_end: Seconds to the last audio packet, or None when the file has no audio.
    """

    video_end: float
    audio_end: float | None

    @property
    def is_audio_only_tail(self) -> bool:
        """Whether the picture stops well before the sound (an ED over a fade to black)."""
        return self.audio_end is not None and self.audio_end - self.video_end > AUDIO_ONLY_TAIL_MIN_S

    @property
    def content_end(self) -> float:
        """The furthest point any stream reaches: the file's real length."""
        return max(self.video_end, self.audio_end or 0.0)


def _probe_stream_ends(media_path: str) -> _StreamEnds | None:
    """Read where every stream really stops, in one ffprobe run; None when the file can't be read.

    ONE run answers three questions the check may need — is the tail audio only, does the file really hold what its
    runtime claims, and where does the picture end — because over a ``.strm`` cloud link every extra call is another
    HTTP request against a share that may be throttling.

    No ``-select_streams``: it takes a single specifier (``v:0,a:0`` is rejected as invalid), and asking for every
    stream costs nothing here since the output is only packet timestamps.
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
        "-show_entries",
        "packet=stream_index,pts_time",
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
    ends: dict[str, float] = {}
    for line in proc.stdout.splitlines():
        parts = [part.strip() for part in line.strip().split(",")]
        if len(parts) < 2 or parts[0] in ("", "N/A") or parts[1] in ("", "N/A"):
            continue
        try:
            pts = float(parts[1])
        except ValueError:
            continue
        index = parts[0]
        if pts > ends.get(index, float("-inf")):
            ends[index] = pts
    if not ends:
        return None
    # Stream indices, not positions: the video is the lowest index, the audio the furthest of the rest.
    video_end = ends.get("0")
    if video_end is None:
        return None
    audio_end = max((pts for index, pts in ends.items() if index != "0"), default=None)
    return _StreamEnds(video_end=video_end, audio_end=audio_end)


def _video_ends_before_audio(media_path: str) -> float | None:
    """The video's real end when the file's tail is audio-only; None when video and audio end together.

    Plenty of releases end with an outro or ED playing over a fade to black, so the video stream stops minutes before
    the container does. Judging such a file by the container's duration demands thumbnails for a stretch that has no
    picture to make them from, so its preview can never satisfy the check and gets rebuilt on every run, forever.

    Returns:
        The video's end in seconds when the audio runs on well past it (the file is fine; measure it by its video), or
        None when they end together (the runtime is the truth) or either end can't be read.
    """
    ends = _probe_stream_ends(media_path)
    return ends.video_end if ends is not None and ends.is_audio_only_tail else None


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
    preview = Path(preview_path)
    try:
        metadata = read_bif_metadata(str(preview))
    except (OSError, ValueError) as exc:
        return PreviewProblem(
            media_path=media_path,
            preview_path=preview_path,
            reason=f"预览文件无法读取：{exc}",
            frames=0,
            expected_frames=None,
        )
    if metadata.frame_count <= 0:
        return PreviewProblem(
            media_path=media_path,
            preview_path=preview_path,
            reason="预览文件是空的（0 帧）",
            frames=0,
            expected_frames=None,
        )

    interval_s = max(1, round((metadata.frame_interval_ms or default_interval_s * 1000) / 1000))
    # A known runtime (the media server's own record, or the <name>-mediainfo.json StrmAssistant already wrote) wins:
    # it costs no network request, so a cloud share is never probed repeatedly. Only when there is no known runtime do
    # we read the real .strm URL ourselves — with retries, since that link is what can 403 or serve just the opening.
    if runtime_s is None or runtime_s <= 0:
        runtime_s = _runtime_seconds(media_path)
    expected = _expected_frames(runtime_s, interval_s)
    if expected is None or runtime_s is None:
        # No trustworthy runtime from either the server or ffprobe. Don't silently call a one-frame preview healthy:
        # a preview that covers only a handful of intervals cannot be the preview of any full-length video. This is the
        # case a .strm link returning 403 lands in, and exactly the broken previews this audit was written to find.
        covered_s = metadata.frame_count * interval_s
        if covered_s < MIN_PLAUSIBLE_COVERAGE_S:
            return PreviewProblem(
                media_path=media_path,
                preview_path=preview_path,
                reason=(
                    f"只有 {metadata.frame_count} 张缩略图（覆盖约 {covered_s / 60:.0f} 分钟），"
                    f"且读不到视频时长（网络源可能拒绝访问）；预览图只覆盖了开头，无法对应任何正常长度的视频"
                ),
                frames=metadata.frame_count,
                expected_frames=None,
            )
        return None
    covered_s = metadata.frame_count * interval_s
    if runtime_s < MIN_AUDIT_DURATION_S:
        # A *network* probe that reports only a few seconds is the cloud share serving just the opening, not a real
        # short film; such a bogus "runtime" must never bless a preview that also covers only a handful of intervals.
        # A genuinely short local clip is different: its runtime is trustworthy, so it is skipped as before.
        if is_network_input(media_path) and covered_s < MIN_PLAUSIBLE_COVERAGE_S:
            return PreviewProblem(
                media_path=media_path,
                preview_path=preview_path,
                reason=(
                    f"只有 {metadata.frame_count} 张缩略图（覆盖约 {covered_s / 60:.0f} 分钟），"
                    f"探测到的时长也只有 {runtime_s / 60:.0f} 分钟（网络源很可能只返回了开头）；"
                    f"预览图和时长都不完整，无法对应正常视频"
                ),
                frames=metadata.frame_count,
                expected_frames=expected,
            )
        return None
    shortfall_s = runtime_s - covered_s
    share = metadata.frame_count / expected
    if share > MAX_HEALTHY_FRAME_SHARE:
        # The BIF says its frames are one interval apart, but it holds far more of them than the file has intervals: it
        # was written by something that didn't know the runtime (every frame the same picture, at a fraction of the
        # stated interval) or at a different interval than its name claims.
        return PreviewProblem(
            media_path=media_path,
            preview_path=preview_path,
            reason=(
                f"缩略图数量异常：{metadata.frame_count} 张（{metadata.file_size / 1024 / 1024:.0f} MB），"
                f"约为视频时长 {runtime_s / 60:.0f} 分钟所需 {expected:.0f} 张的 {share:.0%}，"
                f"超出正常范围（可能是旧版 FFmpeg 读不到时长，一直重复同一张图）"
            ),
            frames=metadata.frame_count,
            expected_frames=expected,
        )
    if _covers_its_run(metadata.frame_count, expected) and shortfall_s <= SHORTFALL_TOLERANCE_S:
        return None
    # Short by the runtime — but the runtime is second-hand (the media server's record, or a StrmAssistant json
    # written when the file was first added), so before calling this a failed run, measure what the file really holds.
    # One ffprobe pass answers all of it: where the picture stops, where the sound stops, and therefore whether the
    # runtime we were given still describes this file. Only a preview that already looks short pays for it.
    ends = _probe_stream_ends(media_path)
    if ends is not None:
        # 1. An outro/ED over a fade: the picture stops minutes before the container does, so thumbnails for the tail
        #    would be pictures that don't exist. Judge the preview by the picture instead.
        if ends.is_audio_only_tail:
            video_expected = _expected_frames(ends.video_end, interval_s)
            if (
                _covers_its_run(metadata.frame_count, video_expected)
                and ends.video_end - covered_s <= SHORTFALL_TOLERANCE_S
            ):
                logger.info(
                    "Preview check: {} covers the picture ({} of {} frames for {:.0f} min of video); the file's last "
                    "{:.0f} min is audio only, so its preview is complete",
                    Path(media_path).name,
                    metadata.frame_count,
                    f"{video_expected:.0f}",
                    ends.video_end / 60,
                    (runtime_s - ends.video_end) / 60,
                )
                return None
        # 2. A stale runtime: the file was replaced or re-encoded after the record was written, so it is shorter than
        #    it claims. Judging by the old figure asks for frames the file cannot produce, rebuilding it every run.
        real_expected = _expected_frames(ends.content_end, interval_s)
        if (
            ends.content_end < runtime_s - SHORTFALL_TOLERANCE_S
            and _covers_its_run(metadata.frame_count, real_expected)
            and ends.content_end - covered_s <= SHORTFALL_TOLERANCE_S
        ):
            logger.info(
                "Preview check: {} covers the whole file ({} of {} frames for its real {:.0f} min); the recorded "
                "runtime of {:.0f} min is out of date, so its preview is complete",
                Path(media_path).name,
                metadata.frame_count,
                f"{real_expected:.0f}",
                ends.content_end / 60,
                runtime_s / 60,
            )
            return None
    return PreviewProblem(
        media_path=media_path,
        preview_path=preview_path,
        reason=(
            f"只有 {metadata.frame_count} 张缩略图（约 {covered_s / 60:.0f} 分钟），"
            f"而视频时长 {runtime_s / 60:.0f} 分钟，应有约 {expected:.0f} 张"
            f"，缺 {shortfall_s / 60:.0f} 分钟"
        ),
        frames=metadata.frame_count,
        expected_frames=expected,
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
