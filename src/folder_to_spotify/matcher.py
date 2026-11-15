import re
import unicodedata
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from typing import Literal

from folder_to_spotify.metadata import Song

MatchMode = Literal["strict", "song"]

MatchStatus = Literal["matched", "review", "unmatched"]

_RELEASE_LABEL = re.compile(
    r"(?:"
    r"(?:\d{4} )?remaster(?:ed)?(?: \d{4})?"
    r"|(?:mono|stereo)(?: version)?"
    r"|single version"
    r")"
)

_TITLE_SUFFIX = re.compile(
    r"^(.*?)"
    r"(?:"
    r"\s+[-–—]\s+([^()\[\]]+)"
    r"|\s*\(([^()]*)\)"
    r"|\s*\[([^\[\]]*)\]"
    r")$"
)


@dataclass(frozen=True)
class Candidate:
    track: dict
    score: float
    title_similarity: float
    artist_similarity: float | None
    album_similarity: float | None
    duration_difference: float | None


@dataclass(frozen=True)
class MatchResult:
    status: MatchStatus
    candidates: list[Candidate]
    reasons: list[str]

    @property
    def selected_uri(self) -> str | None:
        if self.status != "matched":
            return None
        return self.candidates[0].track["uri"]


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = value.replace("&", " and ")
    value = re.sub(r"[^\w\s]", " ", value)
    value = value.replace("_", " ")
    return " ".join(value.split())


def song_title(title: str) -> str:
    while match := _TITLE_SUFFIX.fullmatch(title):
        label = next(group for group in match.groups()[1:] if group is not None)

        if not _RELEASE_LABEL.fullmatch(normalize(label)):
            break

        base = match.group(1).strip()
        if not base:
            break

        title = base

    return title


def normalize_artist(value: str) -> str:
    return normalize(value).removeprefix("the ")


def similarity(left: str, right: str) -> float:
    left = normalize(left)
    right = normalize(right)

    if not left or not right:
        return 0.0

    return SequenceMatcher(None, left, right, autojunk=False).ratio()


def rank_candidate(song: Song, track: dict) -> Candidate:
    title_score = similarity(song.title, track["name"])

    artist_names = [artist["name"] for artist in track["artists"]]

    # Compare with individual artists and the full artist credit
    artist_score = None
    if song.artist:
        artist_options = artist_names + [", ".join(artist_names)]
        local_artist = normalize_artist(song.artist)
        artist_score = max(
            (
                similarity(local_artist, normalize_artist(name))
                for name in artist_options
            ),
            default=0.0,
        )

    album_score = None
    if song.album:
        album_score = similarity(song.album, track["album"]["name"])

    duration_difference = None
    duration_score = None
    duration_ms = track.get("duration_ms")

    if (
        song.duration is not None
        and song.duration > 0
        and duration_ms is not None
        and duration_ms > 0
    ):
        duration_difference = abs(song.duration - duration_ms / 1000)

        if duration_difference <= 3:
            duration_score = 1.0
        else:
            # Gradually reduce the score -> 0 at 15 seconds
            duration_score = max(0.0, (15 - duration_difference) / 12)

    signals = [
        (title_score, 0.45),
        (artist_score, 0.30),
        (duration_score, 0.2),
        (album_score, 0.05),
    ]

    # Missing metadata contributes neither points nor weight
    available = [(value, weight) for value, weight in signals if value is not None]
    score = sum(value * weight for value, weight in available)
    score /= sum(weight for _, weight in available)

    return Candidate(
        track=track,
        score=score,
        title_similarity=title_score,
        artist_similarity=artist_score,
        album_similarity=album_score,
        duration_difference=duration_difference,
    )


def song_candidate(song: Song, track: dict) -> Candidate:
    candidate = rank_candidate(
        replace(song, title=song_title(song.title)),
        {**track, "name": song_title(track["name"])},
    )

    return replace(candidate, track=track)


def song_review_reasons(song: Song, candidate: Candidate) -> list[str]:
    reasons = []

    if song.title_from_filename:
        reasons.append("Title was inferred from the filename")

    if candidate.title_similarity < 1.0:
        reasons.append("Base title or version does not match")

    if candidate.artist_similarity is None:
        reasons.append("Local artist is missing")
    elif candidate.artist_similarity < 1.0:
        reasons.append("Artist is not an exact normalized match")

    if candidate.duration_difference is None:
        reasons.append("Duration is missing or invalid")
    elif candidate.duration_difference > 3:
        reasons.append(f"Duration differs by {candidate.duration_difference:.1f}s")

    if candidate.track.get("is_playable") is False:
        reasons.append("Spotify marks this candidate as unplayable")

    return reasons


def match_song(
    song: Song, tracks: list[dict], *, mode: MatchMode = "strict"
) -> MatchResult:
    if mode == "strict":
        return match_strict(song, tracks)

    if mode == "song":
        return match_song_releases(song, tracks)

    raise ValueError(f"Unknown match mode: {mode}")


def match_song_releases(song: Song, tracks: list[dict]) -> MatchResult:
    unique_tracks = {track["uri"]: track for track in tracks}

    ranked = sorted(
        (song_candidate(song, track) for track in unique_tracks.values()),
        key=lambda candidate: (
            -candidate.score,
            candidate.track["uri"],
        ),
    )

    if not ranked:
        return MatchResult(
            status="unmatched",
            candidates=[],
            reasons=["No candidates returned for this query"],
        )

    eligible = [
        candidate for candidate in ranked if not song_review_reasons(song, candidate)
    ]

    if not eligible:
        return MatchResult(
            status="review",
            candidates=ranked,
            reasons=song_review_reasons(song, ranked[0]),
        )

    eligible.sort(
        key=lambda candidate: (
            -(
                candidate.album_similarity
                if candidate.album_similarity is not None
                else float("inf")
            ),
            (
                candidate.duration_difference
                if candidate.duration_difference is not None
                else float("inf")
            ),
            candidate.track["uri"],
        )
    )

    best = eligible[0]

    # MatchedResult.selected_uri and the cli expect the chosen track first
    ordered = [best] + [candidate for candidate in ranked if candidate is not best]

    if any(not same_song_release(best, candidate) for candidate in eligible[1:]):
        return MatchResult(
            status="review",
            candidates=ordered,
            reasons=[
                "Multiple acceptable candidates have different or missing artist identities"
            ],
        )

    return MatchResult(
        status="matched",
        candidates=ordered,
        reasons=[
            "Song match; exact release uncertain; "
            "Base title and artist match; duration is within 3s; "
            "Selected by album similarity, then duration"
        ],
    )


def match_strict(song: Song, tracks: list[dict]) -> MatchResult:
    # Avoid treating repeated copies of one spotify result as competition
    unique_tracks = {track["uri"]: track for track in tracks}

    ranked = sorted(
        (rank_candidate(song, track) for track in unique_tracks.values()),
        key=lambda candidate: (
            -candidate.score,
            (
                candidate.duration_difference
                if candidate.duration_difference is not None
                else float("inf")
            ),
            candidate.track["uri"],
        ),
    )

    if not ranked:
        return MatchResult(
            status="unmatched",
            candidates=[],
            reasons=["No candidates returned for this query"],
        )

    best = ranked[0]
    reasons = []

    if song.title_from_filename:
        reasons.append("Title was inferred from the filename")

    if best.title_similarity < 1.0:
        reasons.append("Title is not an exact normalized match")

    if best.artist_similarity is None:
        reasons.append("Local artist is missing")
    elif best.artist_similarity < 1.0:
        reasons.append("Artist is not an exact normalized match")

    if best.duration_difference is None:
        reasons.append("Duration is missing or invalid")
    elif best.duration_difference > 3:
        reasons.append(f"Duration differs by {best.duration_difference:.1f}s")

    if best.track.get("is_playable") is False:
        reasons.append("Spotfy marks this candidate as unplayable")

    competitor = strongest_competitor(ranked)
    if competitor is not None:
        margin = best.score - competitor.score

        if margin < 0.03:
            reasons.append(
                "Another candidate outside the equivalent release group has a very similar score"
            )

    if reasons:
        return MatchResult(
            status="review",
            candidates=ranked,
            reasons=reasons,
        )

    return MatchResult(
        status="matched",
        candidates=ranked,
        reasons=[
            "Title and artist match; duration is within 3s; no close competing candidate outside equivalent releases"
        ],
    )


def same_recording(left: dict, right: dict) -> bool:
    left_isrc = (left.get("external_ids") or {}).get("isrc")
    right_isrc = (right.get("external_ids") or {}).get("isrc")

    # missing identifiers must never count as a match
    if not left_isrc or left_isrc != right_isrc:
        return False

    if normalize(left["name"]) != normalize(right["name"]):
        return False

    left_artists = {artist["id"] for artist in left["artists"] if artist.get("id")}
    right_artists = {artist["id"] for artist in right["artists"] if artist.get("id")}

    if not left_artists or left_artists != right_artists:
        return False

    left_duration = left.get("duration_ms")
    right_duration = right.get("duration_ms")

    if left_duration is None or right_duration is None:
        return False

    return (
        left_duration > 0
        and right_duration > 0
        and abs(left_duration - right_duration) <= 3000
    )


def same_song_release(left: Candidate, right: Candidate) -> bool:
    left_ids = {artist["id"] for artist in left.track["artists"] if artist.get("id")}
    right_ids = {artist["id"] for artist in right.track["artists"] if artist.get("id")}

    return (
        bool(left_ids)
        and left_ids == right_ids
        and normalize(song_title(left.track["name"]))
        == normalize(song_title(right.track["name"]))
    )


def strongest_competitor(ranked: list[Candidate]) -> Candidate | None:
    if not ranked:
        return None

    best = ranked[0]

    return next(
        (
            candidate
            for candidate in ranked[1:]
            if not same_recording(best.track, candidate.track)
        ),
        None,
    )
