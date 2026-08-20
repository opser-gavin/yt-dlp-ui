"""Parse progress lines emitted by yt-dlp with our custom template.

The custom template we pass on the command line is:

    --newline
    --progress-template "download:__YDLP__|%(progress.status)s|\
%(progress.downloaded_bytes)s|%(progress.total_bytes)s|\
%(progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s|\
%(info.id)s"

yt-dlp substitutes ``NA`` for unknown values.
"""

from __future__ import annotations

from dataclasses import dataclass

MARKER = "__YDLP__"


@dataclass
class ProgressEvent:
    status: str          # 'downloading' | 'finished' | 'error'
    downloaded: int
    total: int | None    # None if unknown
    speed: float | None  # bytes/sec
    eta: int | None      # seconds
    info_id: str

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
    # status | downloaded | total | total_estimate | speed | eta | id
    if len(parts) < 7:
        return None

    status = parts[0].strip() or "downloading"
    downloaded = _num(parts[1]) or 0
    total = _num(parts[2])
    if total is None:
        total = _num(parts[3])
    speed = _num(parts[4])
    eta = _num(parts[5])
    info_id = parts[6].strip()

    return ProgressEvent(
        status=status,
        downloaded=int(downloaded),
        total=int(total) if total else None,
        speed=speed,
        eta=int(eta) if eta else None,
        info_id=info_id,
    )


PROGRESS_TEMPLATE_ARGS = [
    "--newline",
    "--progress-template",
    (
        f"download:{MARKER}|%(progress.status)s|"
        "%(progress.downloaded_bytes)s|%(progress.total_bytes)s|"
        "%(progress.total_bytes_estimate)s|%(progress.speed)s|"
        "%(progress.eta)s|%(info.id)s"
    ),
]
