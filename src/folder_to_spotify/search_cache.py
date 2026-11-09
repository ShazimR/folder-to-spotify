import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from spotipy import Spotify
from spotipy.exceptions import SpotifyException

CACHE_TTL = 7 * 24 * 60 * 60  # seven days


class SearchPaused(Exception):
    pass


class CacheMiss(Exception):
    pass


class SearchCache:
    def __init__(self) -> None:
        directory = Path.home() / ".cache" / "folder-to-spotify"
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)

        self.path = directory / "search.sqlite3"

        with sqlite3.connect(self.path) as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    saved_at REAL NOT NULL
                )
                """
            )

    def _read(self, key: str):
        with sqlite3.connect(self.path) as db:
            return db.execute(
                "SELECT value, saved_at FROM cache WHERE key = ?",
                (key,),
            ).fetchone()

    def _write(self, key: str, value) -> None:
        with sqlite3.connect(self.path) as db:
            db.execute(
                """
                INSERT OR REPLACE INTO cache (key, value, saved_at)
                VALUES (?, ?, ?)
                """,
                (key, json.dumps(value), time.time()),
            )

    def pause(self, seconds: int | None, reason: str) -> None:
        deadline = time.time() + seconds if seconds is not None else None

        # preserve a longer existing cooldown
        existing = self._read("cooldown")
        if existing:
            old = json.loads(existing[0])
            if old["until"] is None:
                deadline = None
            elif deadline is not None:
                deadline = max(deadline, old["until"])

        self._write("cooldown", {"until": deadline, "reason": reason})

    def _check_cooldown(self) -> None:
        row = self._read("cooldown")
        if row is None:
            return

        cooldown = json.loads(row[0])
        deadline = cooldown["until"]

        if deadline is None:
            raise SearchPaused(
                f"Spotify paused searches: {cooldown['reason']}. "
                "No valid Retry-After was supplied; automatic retries "
                "are disabled. Cached searches remain available."
            )

        remaining = deadline - time.time()
        if remaining > 0:
            resume_at = datetime.fromtimestamp(deadline).astimezone()
            raise SearchPaused(
                f"Spotify searches paused until "
                f"{resume_at:%Y-%m-%d %H:%M:%S %Z} "
                f"({remaining / 3600:.1f} hours remaining). "
                f"Reason: {cooldown['reason']}. "
                "Cached searches remain available."
            )

    def search(
        self,
        spotify: Spotify,
        query: str,
        namespace: str,
        *,
        offline: bool = False,
    ) -> tuple[list[dict], str]:
        key = json.dumps(
            {
                "version": 1,
                "namespace": namespace,
                "query": query,
                "type": "track",
                "limit": 5,
            },
            sort_keys=True,
        )

        row = self._read(key)

        if row is not None:
            data, saved_at = row
            if offline or time.time() - saved_at < CACHE_TTL:
                source = (
                    "cache (expired; offline preview)"
                    if time.time() - saved_at >= CACHE_TTL
                    else "cache"
                )
                return json.loads(data), source

        if offline:
            raise CacheMiss("No cached response for this query")

        # cached results are usable even during spotify cooldown
        self._check_cooldown()

        try:
            response = spotify.search(
                q=query,
                type="track",
                limit=5,
            )
        except SpotifyException as e:
            if e.http_status != 429:
                raise

            headers = e.headers or {}
            raw_delay = headers.get("Retry-After")

            try:
                seconds = max(1, int(raw_delay))
            except (TypeError, ValueError):
                seconds = None

            reason = getattr(e, "reason", None) or "HTTP 429"
            self.pause(seconds, str(reason))
            self._check_cooldown()
            raise  # defensive: never cache an error as an empty result

        tracks = response["tracks"]["items"]
        self._write(key, tracks)
        return tracks, "Spotify API"
