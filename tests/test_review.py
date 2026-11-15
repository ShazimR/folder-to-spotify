import unittest
from unittest.mock import patch

from folder_to_spotify.decisions import Decision
from folder_to_spotify.matcher import Candidate
from folder_to_spotify.review import ReviewResponse, prompt_review


def candidate(uri: str, *, playable: bool = True) -> Candidate:
    return Candidate(
        track={"uri": uri, "is_playable": playable},
        score=1.0,
        title_similarity=1.0,
        artist_similarity=1.0,
        album_similarity=None,
        duration_difference=0.0,
    )


class ReviewPromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidates = [
            candidate("spotify:track:first"),
            candidate("spotify:track:second"),
        ]

    def test_selects_displayed_candidate(self) -> None:
        with patch("builtins.input", return_value="2"):
            response = prompt_review(self.candidates)

        self.assertEqual(
            response,
            ReviewResponse("save", Decision("select", "spotify:track:second")),
        )

    def test_skip(self) -> None:
        with patch("builtins.input", return_value=" S "):
            response = prompt_review(self.candidates)

        self.assertEqual(response, ReviewResponse("save", Decision("skip")))

    def test_enter_leaves_unresolved(self) -> None:
        with patch("builtins.input", return_value=""):
            response = prompt_review(self.candidates)

        self.assertEqual(response, ReviewResponse("later"))

    def test_quit(self) -> None:
        with patch("builtins.input", return_value="q"):
            response = prompt_review(self.candidates)

        self.assertEqual(response, ReviewResponse("quit"))

    def test_reprompts_after_invalid_input(self) -> None:
        with (
            patch(
                "builtins.input",
                side_effect=["hello", "0", "-1", "3", "1"],
            ) as mock_input,
            patch("builtins.print"),
        ):
            response = prompt_review(self.candidates)

        self.assertEqual(mock_input.call_count, 5)
        self.assertEqual(
            response.decision,
            Decision("select", "spotify:track:first"),
        )

    def test_empty_candidates_allow_skip(self) -> None:
        with (
            patch("builtins.input", side_effect=["1", "s"]),
            patch("builtins.print"),
        ):
            response = prompt_review([])

        self.assertEqual(response, ReviewResponse("save", Decision("skip")))

    def test_unplayable_candidate_is_rejected(self) -> None:
        candidates = [candidate("spotify:track:blocked", playable=False)]

        with (
            patch("builtins.input", side_effect=["1", ""]),
            patch("builtins.print"),
        ):
            response = prompt_review(candidates)

        self.assertEqual(response, ReviewResponse("later"))

    def test_interrupted_input_quits(self) -> None:
        for error in (EOFError, KeyboardInterrupt):
            with (
                self.subTest(error=error),
                patch("builtins.input", side_effect=error),
                patch("builtins.print"),
            ):
                response = prompt_review(self.candidates)

                self.assertEqual(response, ReviewResponse("quit"))


if __name__ == "__main__":
    unittest.main()
