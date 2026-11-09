import argparse
from pathlib import Path
import sys

from tinytag import TinyTagException

from folder_to_spotify.metadata import read_song
from folder_to_spotify.scanner import find_music_files


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build Spotify playlists from local music folders."
    )
    parser.add_argument(
        "root",
        type=Path,
        help="Root folder containing your music",
    )
    args = parser.parse_args()

    root = args.root.expanduser().resolve()

    if not root.is_dir():
        parser.error(f"Not a directory: {root}")

    print(f"Scanning: {root}\n")

    found = 0
    read = 0
    failed = 0

    for path in find_music_files(root):
        found += 1

        try:
            song = read_song(path)
        except (OSError, TinyTagException) as e:
            failed += 1
            print(
                f"could not read {path.relative_to(root)}: {e}",
                file=sys.stderr,
            )
            continue

        read += 1

        artist = song.artist or "Unknown artist"
        album = song.album or "Unknown album"
        duration = (
            f"{song.duration:.0f}s"
            if song.duration is not None
            else "Unknown duration"
        )
        fallback = " [filename fallback]" if song.title_from_filename else ""

        print(f"{artist} - {song.title}{fallback}")
        print(f"  Album: {album} | Duration: {duration}")
        print(f"  File: {song.path.relative_to(root)}")

    print(f"\nFound: {found} | Read: {read} | Failed: {failed}")


if __name__ == "__main__":
    main()
