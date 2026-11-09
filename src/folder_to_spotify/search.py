import argparse
import sys
from pathlib import Path

from spotipy import Spotify
from spotipy.exceptions import SpotifyException
from tinytag import TinyTagException

from folder_to_spotify.auth import get_spotify_client
from folder_to_spotify.matcher import match_song
from folder_to_spotify.metadata import Song, read_song
from folder_to_spotify.scanner import find_music_files


def search_text(value: str) -> str:
    # Remove query punctuation while preserving unicde letters and numbers
    return " ".join(
        "".join(char if char.isalnum() else " " for char in value).split()
    )


def find_candidates(spotify: Spotify, song: Song) -> list[dict]:
    title = search_text(song.title)
    artist = search_text(song.artist or "")

    if not title:
        return []

    query = f"track:{title}"
    if artist:
        query += f" artist:{artist}"

    results = spotify.search(q=query, type="track", limit=5)
    return results["tracks"]["items"]


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "Unknown"

    minutes, seconds = divmod(round(seconds), 60)
    return f"{minutes}:{seconds:02d}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preview Spotify candidates for local music files."
    )
    parser.add_argument(
        "root",
        type=Path,
        help="Root music folder"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum number of readable local songs to search (default: 5)",
    )
    args = parser.parse_args()

    root = args.root.expanduser().resolve()
    if not root.is_dir():
        parser.error(f"Not a directory: {root}")
    if args.limit < 1:
        parser.error("--limit must be at least 1")

    try:
        spotify = get_spotify_client()
    except ValueError as e:
        parser.error(str(e))

    searched = 0
    counts = {"matched": 0, "review": 0, "unmatched": 0}

    for path in find_music_files(root):
        try:
            song = read_song(path)
        except (OSError, TinyTagException) as e:
            print(f"Could not read {path}: {e}", file=sys.stderr)
            continue

        print(f"\nFile: {path.relative_to(root)}")
        print(f"Local: {song.artist or 'Unknown artist'} - {song.title}")
        print(f"Duration: {format_duration(song.duration)}")

        if song.title_from_filename:
            print("Title came from the filename")

        try:
            candidates = find_candidates(spotify, song)
        except SpotifyException as e:
            # Stop on API errors instead of reporting songs as unmatched
            raise SystemExit(
                f"spotify search failed (HTTP {e.http_status}): {e.msg}"
            ) from e

        searched += 1

        result = match_song(song, candidates)
        counts[result.status] += 1

        print(f"Decision: {result.status.upper()}")

        for reason in result.reasons:
            print(f"  Reason: {reason}")

        for index, candidate in enumerate(result.candidates, start=1):
            track = candidate.track
            artists = ", ".join(
                artist["name"] for artist in track["artists"]
            )
            duration = track["duration_ms"] / 1000

            selected = (
                " [AUTO_SELECTED]"
                if index == 1 and result.status == "matched"
                else ""
            )

            print(
                f"     Score: {candidate.score * 100:.1f}/100 | "
                f"Album: {track['album']['name']} | "
                f"Duration: {format_duration(duration)}"
            )

            if candidate.duration_difference is not None:
                print(
                    "     Duration difference: "
                    f"{candidate.duration_difference:.1f}s"
                )

            print(f"     {track['external_urls']['spotify']}")

        if searched >= args.limit:
            break

    print(f"\n Previewed {searched} local songs.")
    print(
        f"Matched: {counts['matched']} | "
        f"Review: {counts['review']} | "
        f"Unmatched: {counts['unmatched']}"
    )
    print("dry run: no playlists were changed")


if __name__ == "__main__":
    main()
