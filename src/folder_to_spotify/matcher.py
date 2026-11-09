import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from folder_to_spotify.metadata import Song

MatchStatus = Literal["matched", "review", "unmatched"]


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
        artist_score = max(
            (similarity(song.artist, name) for name in artist_options), default=0.0
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


def match_song(song: Song, tracks: list[dict]) -> MatchResult:
    # Avoid treating repeated copies of one spotify result as competition
    unique_tracks = {track["uri"]: track for track in tracks}

    ranked = sorted(
        (rank_candidate(song, track) for track in unique_tracks.values()),
        key=lambda candidate: candidate.score,
        reverse=True,
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

    if len(ranked) > 1:
        margin = best.score - ranked[1].score

        if margin < 0.03:
            reasons.append("Another candidate has a very similar score")

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
            "Title and artist match; duration is within 3s; candidate has a clear lead"
        ],
    )
