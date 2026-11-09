import argparse
from pathlib import Path

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

    count = 0
    for path in find_music_files(root):
        print(path.relative_to(root))
        count += 1

    print(f'\nFound {count} candidate music files.')


if __name__ == "__main__":
    main()
