import os
import secrets
from pathlib import Path

import spotipy
from spotipy.cache_handler import CacheFileHandler
from spotipy.oauth2 import SpotifyPKCE


REDIRECT_URI = "http://127.0.0.1:8888/callback"

SCOPES = " ".join(
    [
        "playlist-read-private",
        "playlist-modify-private",
        "playlist-modify-public",
    ]
)


def get_spotfy_client() -> spotipy.Spotify:
    client_id = os.environ.get("SPOTIPY_CLIENT_ID", "").strip()

    if not client_id:
        raise ValueError(
            "Set the SPOTIPY_CLIENT_ID environment variable first."
        )

    # Store tokens outside the repo
    cache_dir = Path.home() / ".config" / "folder-to-spotify"
    cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    cache_dir.chmod(0o700)

    cache_name = f"spotify-{client_id}.json"
    cache_handler = CacheFileHandler(
        cache_path=str(cache_dir / cache_name)
    )

    auth_manager = SpotifyPKCE(
        client_id=client_id,
        redirect_uri=REDIRECT_URI,
        scope=SCOPES,
        state=secrets.token_urlsafe(32),
        cache_handler=cache_handler,
        open_browser=False,
        requests_timeout=20,
    )

    return spotipy.Spotify(
        auth_manager=auth_manager,
        requests_timeout=20,
    )


def main() -> None:
    try:
        spotify = get_spotfy_client()
    except ValueError as e:
        raise SystemExit(str(e)) from e

    user = spotify.current_user()
    name = user.get("display_name") or user["id"]

    print(f"Connected to Spotify as {name}.")


if __name__ == "__main__":
    main()
