"""Parse yt-dlp ``--dump-single-json`` output into structured data."""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class FormatInfo:
    format_id: str
    ext: str
    vcodec: str
    acodec: str
    height: int | None
    fps: float | None
    tbr: float | None       # total bitrate (kbps)
    filesize: int | None    # bytes
    note: str

    @property
    def is_video_only(self) -> bool:
        return self.vcodec != "none" and self.acodec == "none"

    @property
    def is_audio_only(self) -> bool:
        return self.vcodec == "none" and self.acodec != "none"

    @property
    def is_muxed(self) -> bool:
        return self.vcodec != "none" and self.acodec != "none"


@dataclass
class SubtitleInfo:
    lang: str
    is_auto: bool           # True for automatic captions
    exts: list[str] = field(default_factory=list)


@dataclass
class MediaInfo:
    url: str
    title: str
    uploader: str
    duration: float | None
    thumbnail: str
    is_playlist: bool
    formats: list[FormatInfo] = field(default_factory=list)
    subtitles: list[SubtitleInfo] = field(default_factory=list)
    # For playlists: list of (title, url) tuples
    entries: list[tuple[str, str]] = field(default_factory=list)


def _f(d: dict, key: str, default=None):
    v = d.get(key)
    return default if v is None else v


def parse(json_text: str, source_url: str) -> MediaInfo:
    """Parse the JSON emitted by ``yt-dlp --dump-single-json``."""
    data = json.loads(json_text)
    is_playlist = data.get("_type") == "playlist" or "entries" in data

    if is_playlist:
        entries = [
            (e.get("title") or e.get("id") or "?", e.get("url") or e.get("webpage_url", ""))
            for e in (data.get("entries") or [])
            if e
        ]
        return MediaInfo(
            url=source_url,
            title=data.get("title") or "(playlist)",
            uploader=data.get("uploader") or "",
            duration=None,
            thumbnail=data.get("thumbnail") or "",
            is_playlist=True,
            entries=entries,
        )

    formats: list[FormatInfo] = []
    for fmt in data.get("formats") or []:
        formats.append(
            FormatInfo(
                format_id=str(fmt.get("format_id") or ""),
                ext=str(fmt.get("ext") or ""),
                vcodec=str(fmt.get("vcodec") or "none"),
                acodec=str(fmt.get("acodec") or "none"),
                height=_f(fmt, "height"),
                fps=_f(fmt, "fps"),
                tbr=_f(fmt, "tbr"),
                filesize=_f(fmt, "filesize") or _f(fmt, "filesize_approx"),
                note=str(fmt.get("format_note") or fmt.get("format") or ""),
            )
        )

    subs: list[SubtitleInfo] = []
    for lang, tracks in (data.get("subtitles") or {}).items():
        subs.append(
            SubtitleInfo(
                lang=lang,
                is_auto=False,
                exts=[t.get("ext", "") for t in tracks if isinstance(t, dict)],
            )
        )
    for lang, tracks in (data.get("automatic_captions") or {}).items():
        # Skip auto-caption langs already covered by real subs
        if any(s.lang == lang for s in subs):
            continue
        subs.append(
            SubtitleInfo(
                lang=lang,
                is_auto=True,
                exts=[t.get("ext", "") for t in tracks if isinstance(t, dict)],
            )
        )

    return MediaInfo(
        url=source_url,
        title=data.get("title") or data.get("id") or "(unknown)",
        uploader=data.get("uploader") or data.get("channel") or "",
        duration=_f(data, "duration"),
        thumbnail=data.get("thumbnail") or "",
        is_playlist=False,
        formats=formats,
        subtitles=subs,
    )


# -------------------------------------------------------- selection helpers

@dataclass
class DownloadSelection:
    """User's picks from the FormatDialog, translated into yt-dlp args."""
    video_format_id: str | None = None
    audio_format_id: str | None = None
    audio_only: bool = False            # -x --audio-format ...
    audio_format: str = "mp3"           # mp3 / m4a / opus ...
    subtitle_langs: list[str] = field(default_factory=list)
    embed_subs: bool = True
    write_thumbnail: bool = False

    def to_args(self) -> list[str]:
        args: list[str] = []
        if self.audio_only:
            args += ["-x", "--audio-format", self.audio_format, "--audio-quality", "0"]
            if self.audio_format_id:
                args += ["-f", self.audio_format_id]
        else:
            fmt: str
            if self.video_format_id and self.audio_format_id:
                fmt = f"{self.video_format_id}+{self.audio_format_id}"
            elif self.video_format_id:
                fmt = self.video_format_id
            else:
                fmt = "bv*+ba/best"
            args += ["-f", fmt]

        if self.subtitle_langs:
            args += ["--write-subs", "--sub-langs", ",".join(self.subtitle_langs)]
            if self.embed_subs:
                args += ["--embed-subs"]

        if self.write_thumbnail:
            args += ["--write-thumbnail"]

        return args
