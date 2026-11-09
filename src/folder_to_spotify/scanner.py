from collections.abc import Iterator
from pathlib import Path

SUPPORTED_EXTENSIONS = {
    ".mp3",
    ".mp4",
    ".m4a",
    ".flac",
    ".wav",
    ".ogg",
    ".opus",
    ".aac",
    ".aiff",
    ".aif",
    ".wma",
}


def find_music_files(root: Path) -> Iterator[Path]:
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield path
