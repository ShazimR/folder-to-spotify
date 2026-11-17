import json
import re
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


_TRACK_URI = re.compile(r"spotify:track:[A-Za-z0-9]{22}")


@dataclass(frozen=True)
class LoadedPlan:
    root: str
    grouping: GroupingMode
    playlists: list[PlannedPlaylist]


def load_plan(source: Path) -> LoadedPlan:
    source = source.expanduser()

    try:
        with source.open(encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Invalid JSON plan: {source}") from e

    if not isinstance(data, dict):
        raise ValueError("Plan mus be a JSON object")

    # bool is subclass of int, so reject true as a version number
    if type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError("Unsupported plan version; expected integer 1")

    root = data.get("root")
    if not isinstance(root, str) or not root.strip():
        raise ValueError("Plan root must be a non-empty string")

    raw_grouping = data.get("grouping")
    grouping: GroupingMode
    if raw_grouping == "single":
        grouping = "single"
    elif raw_grouping == "folders":
        grouping = "folders"
    else:
        raise ValueError("Plan grouping must be 'single' or 'folders'")

    raw_playlists = data.get("playlists")
    if not isinstance(raw_playlists, list):
        raise ValueError("Plan playlists must be a list")

    if grouping == "single" and len(raw_playlists) > 1:
        raise ValueError("Single grouping cannot contain multiple playlists")

    playlists = []

    for index, entry in enumerate(raw_playlists, start=1):
        label = f"Playlist {index}"

        if not isinstance(entry, dict):
            raise ValueError(f"{label} must be an object")

        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{label} mus have a non-empty name")

        raw_uris = entry.get("track_uris")
        if not isinstance(raw_uris, list):
            raise ValueError(f"{label} track_uris must be a list")

        if not raw_uris:
            raise ValueError(f"{label} must contain at least one track")

        uris: list[str] = []
        seen: set[str] = set()

        for track_index, uri in enumerate(raw_uris, start=1):
            if not isinstance(uri, str) or not _TRACK_URI.fullmatch(uri):
                raise ValueError(
                    f"{label}, track {track_index}: invald Spotify rtack URI"
                )

            if uri in seen:
                raise ValueError(f"{label} contains duplicate track URI: {uri}")

            seen.add(uri)
            uris.append(uri)

        playlists.append(PlannedPlaylist(name=name, track_uris=uris))

    return LoadedPlan(
        root=root,
        grouping=grouping,
        playlists=playlists,
    )
