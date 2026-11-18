import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from folder_to_spotify.plan import LoadedPlan


def plan_fingerprint(plan: LoadedPlan) -> str:
    # only include what will actually be published
    payload = [
        {
            "name": playlist.name,
            "track_uris": playlist.track_uris,
        }
        for playlist in plan.playlists
    ]

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest()


class PublishJournal:
    def __init__(self, database: Path | None = None) -> None:
        if database is None:
            database = (
                Path.home()
                / ".local"
                / "share"
                / "folder-to-spotify"
                / "publish.sqlite3"
            )

        database.parent.mkdir(parents=True, exist_ok=True)
        self.database = database

        with closing(sqlite3.connect(database)) as db:
            with db:
                db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS operations (
                        account_id TEXT NOT NULL,
                        plan_hash  TEXT NOT NULL,
                        operation  TEXT NOT NULL,
                        result     TEXT,
                        PRIMARY KEY (account_id, plan_hash, operation)
                    )
                    """
                )

    def begin(self, account_id: str, plan_hash: str, operation: str) -> None:
        with closing(sqlite3.connect(self.database)) as db:
            with db:
                try:
                    db.execute(
                        """
                        INSERT INTO operations (
                            account_id, plan_hash, operation
                        )
                        VALUES (?, ?, ?)
                        """,
                        (account_id, plan_hash, operation),
                    )
                except sqlite3.IntegrityError as e:
                    raise ValueError(f"Operation already recorded: {operation}") from e

    def complete(
        self, account_id: str, plan_hash: str, operation: str, result: dict[str, object]
    ) -> None:
        encoded = json.dumps(result)

        with closing(sqlite3.connect(self.database)) as db:
            with db:
                cursor = db.execute(
                    """
                    UPDATE operations
                    SET result = ?
                    WHERE account_id = ?
                      AND plan_hash = ?
                      AND operation = ?
                      AND result IS NULL
                    """,
                    (encoded, account_id, plan_hash, operation),
                )

        if cursor.rowcount != 1:
            raise ValueError(f"Operation is missing or already complete: {operation}")

    def lookup(
        self, account_id: str, plan_hash: str, operation: str
    ) -> tuple[bool, dict[str, object] | None]:
        with closing(sqlite3.connect(self.database)) as db:
            with db:
                row = db.execute(
                    """
                    SELECT result FROM operations
                    WHERE account_id = ?
                      AND plan_hash = ?
                      AND operation = ?
                    """,
                    (account_id, plan_hash, operation),
                ).fetchone()

        if row is None:
            return False, None

        if row[0] is None:
            return True, None

        return True, json.loads(row[0])

    def reset_plan(
        self, account_id: str, plan_hash: str, *, playlist_index: int | None = None
    ) -> int:
        if playlist_index is not None and playlist_index < 0:
            raise ValueError("playlist_index must be non-negative")

        query = "DELETE FROM operations WHERE account_id = ? AND plan_hash = ?"
        params = [account_id, plan_hash]

        if playlist_index is not None:
            query += " AND operation GLOB ?"
            params.append(f"playlist:{playlist_index}:*")

        with closing(sqlite3.connect(self.database)) as db:
            with db:
                return db.execute(query, params).rowcount
