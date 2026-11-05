# STRM libraries

A `.strm` file is a tiny text file that stands in for a video: Emby and Jellyfin
scan it as a normal movie or episode, and when the player opens it the server
reads the URL inside and streams from there. Cloud drives (rclone, Alist),
HTTP shares and another machine's media folder are usually served this way.

Media Preview Generator reads the `.strm` file, takes the URL (or path) on its
first non-comment line, and hands that to FFmpeg and ffprobe. Everything else
keeps working from the `.strm` path itself:

- Emby's `<name>-<width>-<interval>.bif` sidecar is written beside the `.strm`.
- Jellyfin's `<name>.trickplay/` folder is written beside the `.strm`.
- Plex's bundle hash is calculated from the `.strm` file itself, so Plex must
  index the `.strm` as the media file.
- Skip Intro / Skip Credits, chapter thumbnails and Plex loudness read the same
  URL through the same resolver.

## What a `.strm` file may contain

```text
https://example.com/media/Movies/Heat%20(1995).mkv
```

- One URL per file. Blank lines and lines starting with `#` are ignored.
- `http://`, `https://`, `rtsp://`, `rtmp://`, `rtmps://` and the other
  protocols FFmpeg can read.
- A local path, absolute or relative to the `.strm` file's own folder.
- Another `.strm` file, up to five levels deep.

The URL must be reachable from the container that runs this app. When a worker
node runs the job, it must be reachable from that node: the node reads the
`.strm` file itself, so its own path mappings apply.

## Notes

- MediaInfo opens network URLs only in builds compiled with that support. When
  it can't, the app reads the stream's codec, runtime, HDR format and Dolby
  Vision profile with ffprobe instead, so tone mapping and Dolby Vision still
  work.
- A `.strm` whose URL can't be read fails that file with a message naming the
  problem, and the rest of the queue keeps running.
- Previews are written next to the `.strm` file, so the folder that holds the
  `.strm` files must be writable by the app for Emby and Jellyfin. Plex writes
  into its own data folder as usual.

## Fixing a broken `.strm`

The job's error names the file and the reason: no URL inside, a missing local
target, a Kodi `plugin://` URL (which this app can't resolve), or a chain of
`.strm` files that points at itself. Edit the `.strm` file and run the file
again; no restart is needed.
