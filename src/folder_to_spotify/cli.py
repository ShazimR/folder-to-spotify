import argparse
from pathlib import Path


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

    print(f"Music folder: {root}")
    print(f"Folder scanning is not implemented yet.")


if __name__ == "__main__":
    main()
