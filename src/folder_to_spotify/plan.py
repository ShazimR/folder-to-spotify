import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

GroupingMode = Literal["single", "folders"]


@dataclass
class PlannedPlaylist:
    name: str
    track_uris: list[str] = field(default_factory=list)
    _seen: set[str] = field(default_factory=set, init=False, repr=False)

    def __post_init__(self) -> None:
        # preserve order if initial tracks were supplied
        self.track_uris = list(dict.fromkeys(self.track_uris))
        self._seen = set(self.track_uris)

    def add(self, uri: str) -> bool:
        if uri in self._seen:
            return False

        self._seen.add(uri)
        self.track_uris.append(uri)
        return True


class PlaylistPlan:
    def __init__(self, root: Path, *, grouping: GroupingMode = "single") -> None:
        if grouping not in ("single", "folders"):
            raise ValueError(f"Unknown grouping mode: {grouping}")

        self.root = root.expanduser().resolve()
        self.grouping = grouping
        self._playlists: dict[str, PlannedPlaylist] = {}

    @property
    def playlists(self) -> list[PlannedPlaylist]:
        return list(self._playlists.values())

    def add(self, path: Path, uri: str) -> bool:
        if not uri.startswith("spotify:track:") or not uri.removeprefix(
            "spotify:track:"
        ):
            raise ValueError("Expected a Spotify track URI")

        resolved = path.expanduser().resolve()

        try:
            relative = resolved.relative_to(self.root)
        except ValueError as e:
            raise ValueError(f"File is outsde the music root: {path}") from e

        if not relative.parts:
            raise ValueError("Expected a file path beneath themusic root")

        if self.grouping == "single" or len(relative.parts) == 1:
            key = "."
            name = self.root.name or "Music"
        else:
            key = relative.parts[0]
            name = key

        if key not in self._playlists:
            self._playlists[key] = PlannedPlaylist(name=name)

        return self._playlists[key].add(uri)

    def to_dict(self) -> dict[str, object]:
        return {
            "version": 1,
            "root": str(self.root),
            "grouping": self.grouping,
            "playlists": [
                {
                    "name": playlist.name,
                    "track_uris": list(playlist.track_uris),
                }
                for playlist in self.playlists
            ],
        }

    def save(self, destination: Path) -> None:
        destination = destination.expanduser()

        # serialize before opening the file
        content = json.dumps(
            self.to_dict(),
            indent=2,
            ensure_ascii=False,
        )

        with destination.open("x", encoding="utf-8") as f:
            f.write(content)
            f.write("\n")
