"""Parse progress lines emitted by yt-dlp with our custom template.

Template layout (fields separated by ``|``; the trailing title field may
itself contain ``|`` so it is joined back after splitting)::

    __YDLP__|status|downloaded|total|total_est|speed|eta|id|
             pl_index|pl_count|title
"""

from __future__ import annotations

from dataclasses import dataclass

MARKER = "__YDLP__"


@dataclass
class ProgressEvent:
    status: str            # 'downloading' | 'finished' | 'error'
    downloaded: int
    total: int | None
    speed: float | None
    eta: int | None
    info_id: str
    playlist_index: int | None = None
    playlist_count: int | None = None
    current_title: str = ""

    @property
    def percent(self) -> float | None:
        if not self.total:
            return None
        return min(100.0, self.downloaded / self.total * 100.0)


def _num(s: str) -> float | None:
    if not s or s.upper() == "NA":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse(line: str) -> ProgressEvent | None:
    """Return a ProgressEvent if the line matches our template, else None."""
    idx = line.find(MARKER)
    if idx == -1:
        return None
    body = line[idx + len(MARKER):].lstrip("|")
    parts = body.split("|")
    # 9 fixed fields, plus title at index 9+ (may contain pipes)
    if len(parts) < 10:
        return None

    status = parts[0].strip() or "downloading"
    downloaded = _num(parts[1]) or 0
    total = _num(parts[2])
    if total is None:
        total = _num(parts[3])
    speed = _num(parts[4])
    eta = _num(parts[5])
    info_id = parts[6].strip()
    pl_idx = _num(parts[7])
    pl_cnt = _num(parts[8])
    title = "|".join(parts[9:]).strip()

    return ProgressEvent(
        status=status,
        downloaded=int(downloaded),
        total=int(total) if total else None,
        speed=speed,
        eta=int(eta) if eta else None,
        info_id=info_id,
        playlist_index=int(pl_idx) if pl_idx else None,
        playlist_count=int(pl_cnt) if pl_cnt else None,
        current_title=title,
    )


PROGRESS_TEMPLATE_ARGS = [
    "--newline",
    "--progress-template",
    (
        f"download:{MARKER}|%(progress.status)s|"
        "%(progress.downloaded_bytes)s|%(progress.total_bytes)s|"
        "%(progress.total_bytes_estimate)s|%(progress.speed)s|"
        "%(progress.eta)s|%(info.id)s|"
        "%(info.playlist_index)s|%(info.playlist_count)s|"
        "%(info.title)s"
    ),
]
