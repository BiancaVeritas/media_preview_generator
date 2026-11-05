"""Tests for ``.strm`` library files: the pointer is read, the media behind it is what FFmpeg sees."""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from media_preview_generator import strm
from media_preview_generator.markers import probe


@pytest.fixture(autouse=True)
def _clear_cache():
    strm._target_for_state.cache_clear()
    yield
    strm._target_for_state.cache_clear()


def _write(path: Path, text: str, encoding: str = "utf-8") -> Path:
    path.write_text(text, encoding=encoding)
    return path


def test_is_strm_is_case_insensitive(tmp_path: Path):
    assert strm.is_strm(tmp_path / "Movie.strm")
    assert strm.is_strm(tmp_path / "Movie.STRM")
    assert not strm.is_strm(tmp_path / "Movie.mkv")


def test_http_url_is_read_and_cached(tmp_path: Path):
    pointer = _write(tmp_path / "Movie.strm", "\ufeff  https://example.test/movie.mkv  \n")

    assert strm.media_input(pointer) == "https://example.test/movie.mkv"
    assert strm.resolve(pointer).is_strm is True

    # A rewrite is seen as soon as the file's state changes, not by waiting for a TTL.
    _write(pointer, "https://example.test/other.mkv\n")
    os.utime(pointer, (1_700_000_000, 1_700_000_000))
    assert strm.media_input(pointer) == "https://example.test/other.mkv"


def test_comments_blank_lines_and_quotes_are_skipped(tmp_path: Path):
    media = _write(tmp_path / "S01E01.mkv", "video")
    pointer = _write(tmp_path / "Show.strm", '# made by the importer\n\n"S01E01.mkv"\n')

    assert strm.media_input(pointer) == str(media)


def test_relative_path_resolves_beside_the_pointer(tmp_path: Path):
    (tmp_path / "Movies").mkdir()
    media = _write(tmp_path / "Movies" / "Film.mkv", "not really a video")
    pointer = _write(tmp_path / "Movies" / "Film.strm", "Film.mkv\n")

    assert strm.media_input(pointer) == str(media)


def test_nested_strm_is_followed(tmp_path: Path):
    media = _write(tmp_path / "real.mkv", "video")
    _write(tmp_path / "inner.strm", "real.mkv")
    outer = _write(tmp_path / "outer.strm", "inner.strm")

    assert strm.media_input(outer) == str(media)


def test_strm_loop_says_so(tmp_path: Path):
    a = _write(tmp_path / "a.strm", "b.strm")
    _write(tmp_path / "b.strm", "a.strm")

    with pytest.raises(strm.StrmError, match="itself|more than"):
        strm.media_input(a)


def test_empty_strm_is_an_error(tmp_path: Path):
    pointer = _write(tmp_path / "Empty.strm", "\n# only a comment\n")

    with pytest.raises(strm.StrmError, match="no URL or path"):
        strm.media_input(pointer)


def test_missing_local_target_is_an_error(tmp_path: Path):
    pointer = _write(tmp_path / "Gone.strm", "gone.mkv\n")

    with pytest.raises(strm.StrmError, match="missing file"):
        strm.media_input(pointer)


def test_a_remote_strm_target_is_refused(tmp_path: Path):
    pointer = _write(tmp_path / "Remote.strm", "https://example.test/another.strm\n")

    with pytest.raises(strm.StrmError, match="another STRM file"):
        strm.media_input(pointer)


def test_kodi_plugin_url_is_refused(tmp_path: Path):
    pointer = _write(tmp_path / "Addon.strm", "plugin://plugin.video.example/?url=x\n")

    with pytest.raises(strm.StrmError, match="Kodi"):
        strm.media_input(pointer)


def test_missing_strm_is_an_error(tmp_path: Path):
    with pytest.raises(strm.StrmError, match="couldn't be read"):
        strm.media_input(tmp_path / "Nope.strm")


def test_plain_media_path_is_returned_unchanged(tmp_path: Path):
    media = _write(tmp_path / "Movie.mkv", "video")

    assert strm.media_input(media) == str(media)
    assert strm.ffmpeg_input(media) == str(media)
    assert strm.ffmpeg_input(media, always_protocol=True) == f"file:{media}"


def test_ffmpeg_input_gives_the_url_for_a_strm(tmp_path: Path):
    pointer = _write(tmp_path / "Movie.strm", "https://example.test/movie.mkv\n")

    assert strm.ffmpeg_input(pointer) == "https://example.test/movie.mkv"
    assert strm.ffmpeg_input(pointer, always_protocol=True) == "https://example.test/movie.mkv"


def test_ffprobe_is_given_the_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pointer = _write(tmp_path / "Movie.strm", "https://example.test/movie.mkv\n")
    seen: list[list[str]] = []

    class _Proc:
        returncode = 0

        def communicate(self, timeout=None):
            return "{}", ""

    def fake_popen(cmd, **_kwargs):
        seen.append(list(cmd))
        return _Proc()

    monkeypatch.setattr(probe.subprocess, "Popen", fake_popen)
    probe._run_ffprobe(["ffprobe", "-v", "error", str(pointer)], str(pointer), 5)

    assert seen[0][-1] == "https://example.test/movie.mkv"


def test_ffprobe_error_names_the_broken_strm(tmp_path: Path):
    pointer = _write(tmp_path / "Broken.strm", "")
    with pytest.raises(probe.ProbeError, match="no URL or path"):
        probe._run_ffprobe(["ffprobe", str(pointer)], str(pointer), 5)


@pytest.mark.integration
def test_probe_media_reads_a_video_served_over_http(tmp_path: Path):
    ffprobe = shutil.which("ffprobe")
    ffmpeg = shutil.which("ffmpeg")
    if not ffprobe or not ffmpeg:
        pytest.skip("ffmpeg/ffprobe not installed")

    media = tmp_path / "clip.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=160x120:rate=10:duration=3",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(media),
        ],
        check=True,
        timeout=120,
    )
    handler = lambda *args, **kwargs: SimpleHTTPRequestHandler(*args, directory=str(tmp_path), **kwargs)  # noqa: E731
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/clip.mp4"
        pointer = _write(tmp_path / "Clip.strm", url + "\n")

        probed = probe.probe_media(str(pointer), ffprobe=ffprobe, timeout_s=30)

        assert probed.duration_ms is not None
        assert 2_500 <= probed.duration_ms <= 3_500
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.integration
def test_generate_images_reads_the_stream_and_writes_previews(tmp_path: Path):
    """The whole preview path: a .strm path goes in, JPEGs come out, and the .strm stays the output's neighbour."""
    from unittest.mock import MagicMock

    from media_preview_generator.processing.generator import generate_images

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe not installed")

    media = tmp_path / "clip.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=160x120:rate=10:duration=4",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(media),
        ],
        check=True,
        timeout=120,
    )
    handler = lambda *args, **kwargs: SimpleHTTPRequestHandler(*args, directory=str(tmp_path), **kwargs)  # noqa: E731
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        pointer = _write(tmp_path / "Clip.strm", f"http://127.0.0.1:{server.server_port}/clip.mp4\n")
        out = tmp_path / "frames"
        out.mkdir()
        config = MagicMock()
        config.plex_bif_frame_interval = 1
        config.thumbnail_quality = 4
        config.tmp_folder = str(tmp_path)
        config.ffmpeg_path = ffmpeg
        config.ffmpeg_threads = 2
        config.tonemap_algorithm = "hable"

        success, count, *_rest = generate_images(str(pointer), str(out), None, None, config)

        assert success is True
        assert count >= 3
    finally:
        server.shutdown()
        server.server_close()
