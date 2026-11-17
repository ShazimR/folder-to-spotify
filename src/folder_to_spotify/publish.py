import argparse
from pathlib import Path

from spotipy import Spotify

from folder_to_spotify.plan import LoadedPlan, load_plan
from folder_to_spotify.publish_state import PublishJournal


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

    for offset in range(0, len(track_uris), 100):
        batch = track_uris[offset : offset + 100]
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate and preview a saved Spotify playlist plan"
    )
    parser.add_argument(
        "plan",
        type=Path,
        help="Path to an exported JSON playlist plan",
    )
    args = parser.parse_args()

    try:
        plan = load_plan(args.plan)
    except (OSError, ValueError) as e:
        parser.error(str(e))

    print(describe_plan(plan))

    if not plan.playlists:
        print("Nothing to publish")
        return

    print("Preview only, no Spotify requests were made")


if __name__ == "__main__":
    main()
