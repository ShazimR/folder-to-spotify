from dataclasses import dataclass
from pathlib import Path

from tinytag import TinyTag


@dataclass(frozen=True)
class Song:
    path: Path
    title: str
    artist: str | None
    album: str | None
    duration: float | None
    title_from_filename: bool


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None

    return value.strip() or None


def read_song(path: Path) -> Song:
    tags = TinyTag.get(path)

    title = clean_text(tags.title)
    title_from_filename = title is None

    return Song(
        path=path,
        title=title or path.stem,
        artist=clean_text(tags.artist),
        album=clean_text(tags.album),
        duration=tags.duration,
        title_from_filename=title_from_filename,
    )
