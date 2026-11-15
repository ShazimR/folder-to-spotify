import argparse
import os
import sys
from pathlib import Path
from typing import cast

from spotipy import Spotify
from spotipy.exceptions import SpotifyException
from tinytag import TinyTagException

from folder_to_spotify.auth import get_spotify_client
from folder_to_spotify.decisions import DecisionStore
from folder_to_spotify.matcher import MatchMode, match_song, strongest_competitor
from folder_to_spotify.metadata import Song, read_song
from folder_to_spotify.review import prompt_review
from folder_to_spotify.scanner import find_music_files
from folder_to_spotify.search_cache import CacheMiss, SearchCache, SearchPaused


def search_text(value: str) -> str:
    # Remove query punctuation while preserving unicde letters and numbers
    return " ".join("".join(char if char.isalnum() else " " for char in value).split())


def find_candidates(
    spotify: Spotify,
    song: Song,
    cache: SearchCache,
    namespace: str,
    *,
    offline: bool = False,
) -> tuple[list[dict], str]:
    title = search_text(song.title)
    artist = search_text(song.artist or "")

    if not title:
        return [], "no usable title"

    query = f"track:{title}"
    if artist:
        query += f" artist:{artist}"

    return cache.search(
        spotify,
        query,
        namespace,
        offline=offline,
    )


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "Unknown"

    minutes, seconds = divmod(round(seconds), 60)
    return f"{minutes}:{seconds:02d}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preview Spotify candidates for local music files."
    )
    parser.add_argument("root", type=Path, help="Root music folder")
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum number of readable local songs to search (default: 5)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use saved search results only; make no Spotify requests",
    )
    parser.add_argument(
        "--match-mode",
        choices=("strict", "song"),
        default="strict",
        help=(
            "strict: conservative recording matching (default); "
            "song: allow compatible releases"
        ),
    )
    parser.add_argument(
        "--review",
        action="store_true",
        help="Interactively revew uncertain and unmatched songs",
    )
    args = parser.parse_args()

    if args.review and (not sys.stdin.isatty() or not sys.stdout.isatty()):
        parser.error("--review requres an interactive terminal")

    mode = cast(MatchMode, args.match_mode)
    print(f"Match mode: {mode}")

    root = args.root.expanduser().resolve()
    if not root.is_dir():
        parser.error(f"Not a directory: {root}")
    if args.limit < 1:
        parser.error("--limit must be at least 1")

    try:
        spotify = get_spotify_client()
    except ValueError as e:
        parser.error(str(e))

    cache = SearchCache()
    namespace = os.environ["SPOTIPY_CLIENT_ID"].strip()

    searched = 0
    counts = {"matched": 0, "review": 0, "unmatched": 0}
    cache_misses = 0

    decisions = DecisionStore()
    processed = 0
    saved_selections = 0
    saved_skips = 0
    new_selections = 0
    new_skips = 0

    for path in find_music_files(root):
        if processed >= args.limit:
            break

        try:
            song = read_song(path)
        except (OSError, TinyTagException) as e:
            print(f"Could not read {path}: {e}", file=sys.stderr)
            continue

        processed += 1

        print(f"\nFile: {path.relative_to(root)}")
        print(f"Local: {song.artist or 'Unknown artist'} - {song.title}")
        print(f"Duration: {format_duration(song.duration)}")

        if song.title_from_filename:
            print("Title came from the filename")

        saved = decisions.get(path)
        if saved is not None:
            if saved.action == "select":
                saved_selections += 1
                print("Decision: SAVED SELECTION")
                print(f"  Spotify URI: {saved.spotify_uri}")
            else:
                saved_skips += 1
                print("Decision: SAVED SKIP")

            continue

        try:
            candidates, source = find_candidates(
                spotify,
                song,
                cache,
                namespace,
                offline=args.offline,
            )
        except CacheMiss:
            cache_misses += 1
            print("Decision: NOT SEARCHED - no cached response")
            continue
        except SearchPaused as e:
            raise SystemExit(
                f"\n{e}\n"
                "Stopped. Completed searches were saved; "
                "rerun the same command after the cooldown."
            ) from e
        except SpotifyException as e:
            raise SystemExit(
                f"Spotify search failed (HTTP {e.http_status}): {e.msg}"
            ) from e

        print(f"Search source: {source}")

        searched += 1

        result = match_song(song, candidates, mode=mode)

        if mode == "strict":
            competitor = strongest_competitor(result.candidates)

            if competitor is not None:
                gap = result.candidates[0].score - competitor.score
                print(f"Competing candidate score gap: {gap * 100:.2f} points")
            elif result.candidates:
                print("No competng candidate outside equivalent releases")

        counts[result.status] += 1

        print(f"Decision: {result.status.upper()}")

        for reason in result.reasons:
            print(f"  Reason: {reason}")

        for index, candidate in enumerate(result.candidates, start=1):
            track = candidate.track
            artists = ", ".join(artist["name"] for artist in track["artists"])
            duration = track["duration_ms"] / 1000

            selected = (
                " [AUTO_SELECTED]" if index == 1 and result.status == "matched" else ""
            )

            print(f"  {index}. {artists} - {track['name']}{selected}")
            print(
                f"     Score: {candidate.score * 100:.1f}/100 | "
                f"Album: {track['album']['name']} | "
                f"Duration: {format_duration(duration)}"
            )

            isrc = (track.get("external_ids") or {}).get("isrc")
            print(f"     ISRC: {isrc or 'missing'}")

            artist_score = (
                f"{candidate.artist_similarity:.3f}"
                if candidate.artist_similarity is not None
                else "missing"
            )

            album_score = (
                f"{candidate.album_similarity:.3f}"
                if candidate.album_similarity is not None
                else "missing"
            )

            title_label = "base title" if mode == "song" else "title"
            print(
                f"     Similarities: "
                f"{title_label}={candidate.title_similarity:.3f}, "
                f"artist={artist_score}, "
                f"album={album_score}"
            )

            if candidate.duration_difference is not None:
                print(f"     Duration difference: {candidate.duration_difference:.1f}s")

            print(f"     {track['external_urls']['spotify']}")

        if args.review and result.status in ("review", "unmatched"):
            response = prompt_review(result.candidates)

            if response.action == "quit":
                print("Review stopped; Earlier choices are saved")
                break

            if response.action == "save":
                decision = response.decision
                if decision is None:
                    raise RuntimeError("Save response is missing a decision")

                decisions.save(path, decision)

                if decision.action == "select":
                    new_selections += 1
                    print(f"Saved selection: {decision.spotify_uri}")
                else:
                    new_skips += 1
                    print("Saved skip")
            else:
                print("Left unresolved")

    print(f"\nProcessed {processed} local songs")
    print(f"Evaluated search results for {searched} songs")
    print(f"Not searched (offline cache misses): {cache_misses}")
    print(
        f"Automatic results - "
        f"Matched: {counts['matched']} | "
        f"Review: {counts['review']} | "
        f"Unmatched: {counts['unmatched']}"
    )
    print(f"Reused decisions - Selected:{saved_selections} | Skipped: {saved_skips}")
    print(f"New decsions saved - Selected: {new_selections} | Skipped: {new_skips}")
    print("No playlists were changed")


if __name__ == "__main__":
    main()
