from dataclasses import dataclass
from typing import Literal

from folder_to_spotify.decisions import Decision
from folder_to_spotify.matcher import Candidate

ReviewAction = Literal["save", "later", "quit"]


@dataclass(frozen=True)
class ReviewResponse:
    action: ReviewAction
    decision: Decision | None = None


def prompt_review(candidates: list[Candidate]) -> ReviewResponse:
    if candidates:
        choices = f"1-{len(candidates)}: select | "
    else:
        choices = ""

    prompt = f"{choices}s: skip | Enter: later | q: quit\n> "

    while True:
        try:
            answer = input(prompt).strip().casefold()
        except (EOFError, KeyboardInterrupt):
            print("\nLeaving review")
            return ReviewResponse("quit")

        if not answer:
            return ReviewResponse("later")

        if answer == "q":
            return ReviewResponse("quit")

        if answer == "s":
            return ReviewResponse("save", Decision("skip"))

        try:
            index = int(answer)
        except ValueError:
            print("Enter a candidate number, s, q, or press Enter")
            continue

        if not 1 <= index <= len(candidates):
            print("That candidate number is not available")
            continue

        track = candidates[index - 1].track

        if track.get("is_playable") is False:
            print("Spotify marks this candidate as unplayable")
            continue

        return ReviewResponse("save", Decision("select", track["uri"]))
