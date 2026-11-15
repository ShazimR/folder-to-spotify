import unittest
from pathlib import Path

from folder_to_spotify.matcher import (
    match_song,
    normalize,
    rank_candidate,
    song_candidate,
    song_title,
)
from folder_to_spotify.metadata import Song


class NormalizeTests(unittest.TestCase):
    def test_case_punctuation_and_whitespace(self) -> None:
        self.assertEqual(
            normalize("     HELLO,    World!   "),
            "hello world",
        )

    def test_ampersand_matches_and(self) -> None:
        self.assertEqual(
            normalize("Simon & Garfunkel"),
            normalize("Simon and Garfunkel"),
        )

    def test_unicode_normalization(self) -> None:
        self.assertEqual(
            normalize("Cher"),
            normalize("Ｃｈｅｒ"),
        )


class SongTitleTests(unittest.TestCase):
    def test_removes_recognized_release_labels(self) -> None:
        titles = [
            "Example - Remastered",
            "Example - Remastered 2009",
            "Example - 2009 Remaster",
            "Example (Single Version)",
            "Example [Mono]",
            "Example - Stereo Version",
            "Example – Remastered",
            "Example — Remastered",
        ]

        for title in titles:
            with self.subTest(title=title):
                self.assertEqual(song_title(title), "Example")

    def test_removes_stacked_release_labels(self) -> None:
        self.assertEqual(
            song_title("Example (Remastered) [Mono]"),
            "Example",
        )

    def test_preserves_alternate_versions(self) -> None:
        titles = [
            "Example - Live",
            "Example (Acoustic)",
            "Example [Remix]",
            "Example - Karaoke",
            "Example - Demo",
            "Example - Instrumental",
            "Example - Live Remastered 2009",
        ]

        for title in titles:
            with self.subTest(title=title):
                self.assertEqual(song_title(title), title)

    def test_preserves_meaningful_title_parts(self) -> None:
        titles = [
            "No Matter What Shape (Your Stomach's In)",
            "Example / Another Song",
            "Example - Part Two",
            "Live and Let Die",
            "Remastered",
        ]

        for title in titles:
            with self.subTest(title=title):
                self.assertEqual(song_title(title), title)

    def test_preserves_unknown_labels(self) -> None:
        title = "Example (Special Anniversary Edition)"
        self.assertEqual(song_title(title), title)

    def test_removing_release_label_keeps_version(self) -> None:
        self.assertEqual(
            song_title("Example (Live) [Remastered]"),
            "Example (Live)",
        )

    def test_does_not_strip_entire_title(self) -> None:
        title = "(Remastered)"
        self.assertEqual(song_title(title), title)

    def test_normalization_is_idempotent(self) -> None:
        # applying the helper twice shouldn't chnge its result
        titles = [
            "Example (Remastered) [Mono]",
            "Example - Live",
            "No Matter What Shape (Your Stomach's In)",
        ]

        for title in titles:
            with self.subTest(title=title):
                once = song_title(title)
                self.assertEqual(song_title(once), once)


class SongCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.song = Song(
            path=Path("example.mp3"),
            title="Example",
            artist="Artist",
            album="Album",
            duration=180.0,
            title_from_filename=False,
        )

        self.track = {
            "uri": "spotify:track:example",
            "name": "Example - Remastered 2009",
            "artists": [{"id": "artist-id", "name": "Artist"}],
            "album": {"name": "Album"},
            "duration_ms": 181000,
        }

    def test_song_mode_matches_base_title(self) -> None:
        strict = rank_candidate(self.song, self.track)
        candidate = song_candidate(self.song, self.track)

        self.assertLess(strict.title_similarity, 1.0)
        self.assertEqual(candidate.title_similarity, 1.0)

    def test_other_signals_are_unchanged(self) -> None:
        strict = rank_candidate(self.song, self.track)
        candidate = song_candidate(self.song, self.track)

        self.assertEqual(candidate.artist_similarity, strict.artist_similarity)
        self.assertEqual(candidate.album_similarity, strict.album_similarity)
        self.assertEqual(candidate.duration_difference, 1.0)

    def test_preserves_original_data(self) -> None:
        candidate = song_candidate(self.song, self.track)

        self.assertIs(candidate.track, self.track)
        self.assertEqual(
            candidate.track["name"],
            "Example - Remastered 2009",
        )
        self.assertEqual(self.song.title, "Example")

    def test_live_version_still_differs(self) -> None:
        live_track = {**self.track, "name": "Example - Live"}
        candidate = song_candidate(self.song, live_track)

        self.assertLess(candidate.title_similarity, 1.0)

    def test_song_mode_accepts_remastered_title(self) -> None:
        result = match_song(self.song, [self.track], mode="song")

        self.assertEqual(result.status, "matched")
        self.assertEqual(result.selected_uri, self.track["uri"])

    def test_strict_mode_still_reviews_remastered_title(self) -> None:
        result = match_song(self.song, [self.track], mode="strict")

        self.assertEqual(result.status, "review")
        self.assertIsNone(result.selected_uri)

    def test_song_mode_selects_closest_duration(self) -> None:
        closer = {
            **self.track,
            "uri": "spotify:track:closer",
            "duration_ms": 180100,
        }

        result = match_song(
            self.song,
            [self.track, closer],
            mode="song",
        )

        self.assertEqual(result.status, "matched")
        self.assertEqual(result.selected_uri, closer["uri"])

    def test_song_mode_excludes_bad_duration_before_selection(self) -> None:
        bad_duration = {
            **self.track,
            "uri": "spotify:track:bad-duration",
            "name": "Example",
            "duration_ms": 190000,
        }

        result = match_song(
            self.song,
            [bad_duration, self.track],
            mode="song",
        )

        self.assertEqual(result.status, "matched")
        self.assertEqual(result.selected_uri, self.track["uri"])

    def test_song_mode_reviews_different_artist_identities(self) -> None:
        other_artist = {
            **self.track,
            "uri": "spotify:track:other-artist",
            "artists": [{"id": "dfferent-id", "name": "Artist"}],
        }

        result = match_song(
            self.song,
            [self.track, other_artist],
            mode="song",
        )

        self.assertEqual(result.status, "review")
        self.assertIsNone(result.selected_uri)

    def test_mode_reviews_live_version(self) -> None:
        live = {**self.track, "name": "Example - Live"}

        result = match_song(self.song, [live], mode="song")

        self.assertEqual(result.status, "review")

    def test_song_mode_handles_no_results(self) -> None:
        result = match_song(self.song, [], mode="song")

        self.assertEqual(result.status, "unmatched")
        self.assertIsNone(result.selected_uri)


if __name__ == "__main__":
    unittest.main()
