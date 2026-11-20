import argparse
import sqlite3
from pathlib import Path

from requests.exceptions import RequestException
from spotipy import Spotify
from spotipy.exceptions import SpotifyException

from folder_to_spotify.auth import get_spotify_client
from folder_to_spotify.plan import LoadedPlan, load_plan
from folder_to_spotify.publish_state import PublishJournal, plan_fingerprint

TRACKS_PER_BATCH = 100
LIBRARY_CHECK_BATCH_SIZE = 40


def describe_plan(plan: LoadedPlan) -> str:
    total_tracks = sum(len(playlist.track_uris) for playlist in plan.playlists)

    lines = [
        f"Grouping: {plan.grouping}",
        f"Playlists: {len(plan.playlists)}",
        f"Track placements: {total_tracks}",
    ]

    for index, playlist in enumerate(plan.playlists, start=1):
        lines.append(f"  {index}. {playlist.name}: {len(playlist.track_uris)} tracks")

    return "\n".join(lines)


class PendingPublishError(RuntimeError):
    """A previous request has an unknown outcome"""


def ensure_playlist(
    spotify: Spotify,
    journal: PublishJournal,
    *,
    account_id: str,
    plan_hash: str,
    playlist_index: int,
    name: str,
) -> str:
    operation = f"playlist:{playlist_index}:create"

    exists, result = journal.lookup(account_id, plan_hash, operation)

    if exists:
        if result is None:
            raise PendingPublishError(
                f"Creation outcome is unknown for playlist {name!r}; "
                "Check Spotify before retrying; no new request was sent"
            )

        playlist_id = result.get("playlist_id")
        if not isinstance(playlist_id, str) or not playlist_id:
            raise ValueError(f"Invalid saved playlist ID for operation {operation}")

        return playlist_id

    # commit the intent before making the external request
    journal.begin(account_id, plan_hash, operation)

    response = spotify.current_user_playlist_create(
        name=name, public=False, description="Created with folder-to-spotify"
    )

    if not isinstance(response, dict):
        raise ValueError("Spotify returned an invalid playlist response")

    playlist_id = response.get("id")
    if not isinstance(playlist_id, str) or not playlist_id:
        raise ValueError("Spotfy dd no return a playlist ID")

    journal.complete(account_id, plan_hash, operation, {"playlist_id": playlist_id})

    return playlist_id


def ensure_tracks(
    spotify: Spotify,
    journal: PublishJournal,
    *,
    account_id: str,
    plan_hash: str,
    playlist_index: int,
    playlist_id: str,
    track_uris: list[str],
) -> int:
    added = 0

    for offset in range(0, len(track_uris), TRACKS_PER_BATCH):
        batch = track_uris[offset : offset + TRACKS_PER_BATCH]
        operation = f"playlist:{playlist_index}:add:{offset}"

        exists, result = journal.lookup(account_id, plan_hash, operation)

        if exists:
            if result is None:
                raise PendingPublishError(
                    f"Track addition outcome is unknown for playlist "
                    f"{playlist_id}, starting at track {offset + 1}; "
                    "No retry was sent"
                )

            snapshot_id = result.get("snapshot_id")

            if (
                result.get("playlist_id") != playlist_id
                or result.get("track_uris") != batch
                or not isinstance(snapshot_id, str)
                or not snapshot_id
            ):
                raise ValueError(
                    f"Saved batch does not match this request: {operation}"
                )

            continue

        journal.begin(account_id, plan_hash, operation)

        response = spotify.playlist_add_items(
            playlist_id=playlist_id,
            items=batch,
        )

        if not isinstance(response, dict):
            raise ValueError("Spotify returned an invalid track-add response")

        snapshot_id = response.get("snapshot_id")
        if not isinstance(snapshot_id, str) or not snapshot_id:
            raise ValueError("Spotify did not return a snapshot ID")

        journal.complete(
            account_id,
            plan_hash,
            operation,
            {
                "playlist_id": playlist_id,
                "track_uris": batch,
                "snapshot_id": snapshot_id,
            },
        )

        added += len(batch)

    return added


def get_account_id(spotify: Spotify) -> str:
    user = spotify.current_user()
    if not isinstance(user, dict):
        raise ValueError("Spotify returned an invalid user response")

    account_id = user.get("id")
    if not isinstance(account_id, str) or not account_id:
        raise ValueError("Spotify did not return an account ID")

    return account_id


def playlist_url(playlist_id: str) -> str:
    return f"https://open.spotify.com/playlist/{playlist_id}"


def apply_plan(spotify: Spotify, journal: PublishJournal, plan: LoadedPlan) -> int:
    if not plan.playlists:
        return 0

    account_id = get_account_id(spotify)
    print(f"Spotify account: {account_id}")

    fingerprint = plan_fingerprint(plan)
    total_added = 0

    for index, playlist in enumerate(plan.playlists):
        print(f"\nPublishing: {playlist.name}")

        playlist_id = ensure_playlist(
            spotify,
            journal,
            account_id=account_id,
            plan_hash=fingerprint,
            playlist_index=index,
            name=playlist.name,
        )

        print(f"  {playlist_url(playlist_id)}")

        added = ensure_tracks(
            spotify,
            journal,
            account_id=account_id,
            plan_hash=fingerprint,
            playlist_index=index,
            playlist_id=playlist_id,
            track_uris=playlist.track_uris,
        )

        total_added += added
        print(
            f"  Added this run: {added}; "
            f"previously recorded: {len(playlist.track_uris) - added}"
        )

    return total_added


def verify_plan(spotify: Spotify, journal: PublishJournal, plan: LoadedPlan) -> None:
    account_id = get_account_id(spotify)
    fingerprint = plan_fingerprint(plan)
    print(f"\nChecking Spotify library for {account_id}")

    statuses: dict[int, str] = {}
    recorded: list[tuple[int, str]] = []

    for index, playlist in enumerate(plan.playlists):
        operation = f"playlist:{index}:create"
        exists, result = journal.lookup(account_id, fingerprint, operation)

        if not exists:
            statuses[index] = "NO CREATION RECORD"
            continue
        if result is None:
            statuses[index] = "CREATION PENDING (outcome unknown)"
            continue

        playlist_id = result.get("playlist_id")
        if not isinstance(playlist_id, str) or not playlist_id:
            raise ValueError(f"Invalid saved playlist ID for {playlist.name!r}")

        recorded.append((index, playlist_id))

    for start in range(0, len(recorded), LIBRARY_CHECK_BATCH_SIZE):
        batch = recorded[start : start + LIBRARY_CHECK_BATCH_SIZE]
        flags = spotify.current_user_saved_items(
            [f"spotify:playlist:{playlist_id}" for _, playlist_id in batch]
        )

        if (
            not isinstance(flags, list)
            or len(flags) != len(batch)
            or not all(isinstance(flag, bool) for flag in flags)
        ):
            raise ValueError("Spotify returned an invalid library membership response")

        for (index, playlist_id), present in zip(batch, flags, strict=True):
            state = "IN LIBRARY" if present else "MISSING FROM LIBRARY"
            statuses[index] = f"{state}\n     {playlist_url(playlist_id)}"

    for index, playlist in enumerate(plan.playlists):
        print(f"  {index + 1}. {playlist.name}: {statuses[index]}")


def print_journal_status(
    journal: PublishJournal, plan: LoadedPlan, account_id: str
) -> None:
    fingerprint = plan_fingerprint(plan)
    print(f"Local publish journal for {account_id}")

    for index, playlist in enumerate(plan.playlists):
        print(f"\n{playlist.name}")
        prefix = f"playlist:{index}"
        operations = [(f"{prefix}:create", "Create playlist")]

        for offset in range(0, len(playlist.track_uris), TRACKS_PER_BATCH):
            end = min(offset + TRACKS_PER_BATCH, len(playlist.track_uris))
            operations.append(
                (f"{prefix}:add:{offset}", f"Add tracks {offset + 1}-{end}")
            )

        for key, label in operations:
            exists, result = journal.lookup(account_id, fingerprint, key)
            if not exists:
                state = "NEVER ATTEMPTED"
            elif result is None:
                state = "PENDING (outcome unknown)"
            else:
                state = "COMPLETE"

            print(f"  {label}: {state}")
            if key == f"{prefix}:create" and result is not None:
                playlist_id = result.get("playlist_id")
                if isinstance(playlist_id, str) and playlist_id:
                    print(f"    {playlist_url(playlist_id)}")


def reset_plan_with_urls(
    journal: PublishJournal,
    plan: LoadedPlan,
    account_id: str,
    *,
    playlist_index: int | None = None,
) -> int:
    fingerprint = plan_fingerprint(plan)
    indices = (
        range(len(plan.playlists)) if playlist_index is None else (playlist_index,)
    )

    for index in indices:
        _, result = journal.lookup(account_id, fingerprint, f"playlist:{index}:create")
        if result is None:
            continue

        playlist_id = result.get("playlist_id")
        if isinstance(playlist_id, str) and playlist_id:
            name = plan.playlists[index].name
            print(f"Previously recorded playlist {index + 1}: {name}")
            print(f"  {playlist_url(playlist_id)}", flush=True)

    return journal.reset_plan(account_id, fingerprint, playlist_index=playlist_index)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preview or publish a saved Spotify playlist plan"
    )
    parser.add_argument(
        "plan",
        type=Path,
        help="Path to an exported JSON playlist plan",
    )
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--apply",
        action="store_true",
        help="Create private Spotfy playlists and add the planned tracks",
    )
    actions.add_argument(
        "--status",
        action="store_true",
        help="Show local publish progress for this plan and account",
    )
    actions.add_argument(
        "--reset-journal",
        action="store_true",
        help="Forget all local publish progress for this plan and account",
    )
    actions.add_argument(
        "--verify",
        action="store_true",
        help="Check whether the recorded playlists are in your Spotify library",
    )
    parser.add_argument(
        "--account-id", help="Spotify account ID printed during publishing"
    )
    parser.add_argument(
        "--playlist",
        type=int,
        metavar="NUMBER",
        help="Reset only this playlist, using ts 1-based number in the plan",
    )
    args = parser.parse_args()

    if args.playlist is not None and not args.reset_journal:
        parser.error("--playlist requires --reset-journal")

    account_id = (args.account_id or "").strip()
    if args.status or args.reset_journal:
        if not account_id:
            parser.error("--status and --reset-journal require --account-id")
    elif args.account_id is not None:
        parser.error("--account-id is only used with --status or --reset-journal")

    try:
        plan = load_plan(args.plan)
    except (OSError, ValueError) as e:
        parser.error(str(e))

    print(describe_plan(plan))

    if args.status or args.reset_journal:
        try:
            journal = PublishJournal()
            if args.status:
                print_journal_status(journal, plan, account_id)
            elif args.playlist is not None:
                number = args.playlist
                if not 1 <= number <= len(plan.playlists):
                    parser.error(f"Playlist {number} does not exist in this plan")

                index = number - 1
                removed = reset_plan_with_urls(
                    journal, plan, account_id, playlist_index=index
                )
                print(
                    f"Removed {removed} journal entries for playlist {number} "
                    f"({plan.playlists[index].name})"
                )
            else:
                removed = reset_plan_with_urls(journal, plan, account_id)
                print(f"Removed {removed} journal entries for {account_id}")
        except (OSError, sqlite3.Error, ValueError) as e:
            raise SystemExit(f"Could not access the publish journal: {e}") from e
        return

    if not plan.playlists:
        print("Nothing to publish")
        return

    if not (args.apply or args.verify):
        print("Prevew only; no Spotify requests were made")
        print(
            "Use --apply to publish this plan or use --verify to verify added playlists"
        )
        return

    try:
        spotify = get_spotify_client()
        journal = PublishJournal()
        if args.verify:
            verify_plan(spotify, journal, plan)
            return
        added = apply_plan(spotify, journal, plan)
    except PendingPublishError as e:
        raise SystemExit(f"Publshing paused: {e}") from e
    except SpotifyException as e:
        message = f"Spotify request failed (HTTP {e.http_status})"

        if e.http_status == 429:
            retry_after = (e.headers or {}).get("Retry-After")
            if retry_after is not None:
                message += f"  Retry-After: {retry_after} seconds"

        errMsg = (
            f"{message}\nCompleted operations remain recorded; "
            "an unfinished write may need reconciliation before it can be retried"
            if args.apply
            else f"Verification stopped: {message}"
        )
        raise SystemExit(f"{errMsg}\n") from e
    except (RequestException, OSError, sqlite3.Error, ValueError) as e:
        errMsg = (
            f"Publishing stopped: {e}\nCompleted operations remain recorded; "
            "an unfinished write may need reconciliation before it can be retried"
            if args.apply
            else f"Verification stopped: {e}"
        )
        raise SystemExit(errMsg) from e
    except KeyboardInterrupt:
        errMsg = (
            "\nPublishing interrupted; progress remains recorded; "
            "an in-flight request may have unknown outcome"
            if args.apply
            else "\nVerfication stopped"
        )
        raise SystemExit(errMsg) from None

    print(f"\nPlan operations complete; tracks added to this run {added}")


if __name__ == "__main__":
    main()
