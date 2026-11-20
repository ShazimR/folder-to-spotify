import argparse
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

DecisionAction = Literal["select", "skip"]


@dataclass(frozen=True)
class Decision:
    action: DecisionAction
    spotify_uri: str | None = None

    def __post_init__(self) -> None:
        if self.action == "select":
            if (
                self.spotify_uri is None
                or not self.spotify_uri.startswith("spotify:track")
                or not self.spotify_uri.removeprefix("spotify:track:")
            ):
                raise ValueError("Selecting a track requires a Spotify track URI")
        elif self.action == "skip":
            if self.spotify_uri is not None:
                raise ValueError("A skipped file cannot have a potfy URI")
        else:
            raise ValueError(f"Unknown decision action: {self.action}")


class DecisionStore:
    def __init__(self, database: Path | None = None) -> None:
        if database is None:
            database = (
                Path.home()
                / ".local"
                / "share"
                / "folder-to-spotify"
                / "decisions.sqlite3"
            )

        database.parent.mkdir(parents=True, exist_ok=True)
        self.database = database

        with closing(sqlite3.connect(self.database)) as db:
            with db:
                db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS decisions (
                        path        TEXT    PRIMARY KEY,
                        size_bytes  INTEGER NOT NULL,
                        modified_ns INTEGER NOT NULL,
                        action      TEXT    NOT NULL CHECK (action IN ('select', 'skip')),
                        spotify_uri TEXT,
                        CHECK (
                            (action == 'select' AND spotify_uri IS NOT NULL)
                            OR
                            (action == 'skip' AND spotify_uri IS NULL)
                        )
                    )
                    """
                )

    def get(self, path: Path) -> Decision | None:
        resolved = path.resolve()
        stat = resolved.stat()

        with closing(sqlite3.connect(self.database)) as db:
            with db:
                row = db.execute(
                    """
                    SELECT action, spotify_uri
                    FROM decisions
                    WHERE path = ? AND size_bytes = ? AND modified_ns = ?
                    """,
                    (str(resolved), stat.st_size, stat.st_mtime_ns),
                ).fetchone()

        if row is None:
            return None

        action, uri = row
        if action == "select":
            return Decision("select", uri)
        if action == "skip":
            return Decision("skip")

        raise ValueError(f"Invalid saved decision action: {action}")

    def save(self, path: Path, decision: Decision) -> None:
        resolved = path.resolve()
        stat = resolved.stat()

        with closing(sqlite3.connect(self.database)) as db:
            with db:
                db.execute(
                    """
                    INSERT INTO decisions (
                        path, size_bytes, modified_ns, action, spotify_uri
                    )
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(path) DO UPDATE SET
                        size_bytes  = excluded.size_bytes,
                        modified_ns = excluded.modified_ns,
                        action      = excluded.action,
                        spotify_uri = excluded.spotify_uri
                    """,
                    (
                        str(resolved),
                        stat.st_size,
                        stat.st_mtime_ns,
                        decision.action,
                        decision.spotify_uri,
                    ),
                )

    def forget(self, path: Path) -> bool:
        return self.forget_many([path]) > 0

    def forget_many(self, paths: Iterable[Path]) -> int:
        unique_paths = {str(path.expanduser().resolve()) for path in paths}

        if not unique_paths:
            return 0

        with closing(sqlite3.connect(self.database)) as db:
            with db:
                cursor = db.executemany(
                    "DELETE FROM decisions WHERE path = ?",
                    [(path,) for path in unique_paths],
                )

                return cursor.rowcount


def main(argv: list[str] | None = None, *, prog: str | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog=prog, description="Manage saved song review decisions"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    forget_parser = commands.add_parser(
        "forget",
        help="Remove a saved selection or skip for one file",
    )
    forget_parser.add_argument(
        "files",
        type=Path,
        nargs="+",
        help="Paths to one or more local music files",
    )
    args = parser.parse_args(argv)

    if args.command == "forget":
        store = DecisionStore()
        removed = store.forget_many(args.files)
        print(f"Removed {removed} saved decision(s)")


if __name__ == "__main__":
    main()
