import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from folder_to_spotify.decisions import Decision, DecisionStore


class DecisionStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

        root = Path(self.directory.name)
        self.music_file = root / "example.mp3"
        self.music_file.write_bytes(b"test audio")

        self.database = root / "decisions.sqlite3"
        self.store = DecisionStore(self.database)

    def test_unknown_file_has_no_decision(self) -> None:
        self.assertIsNone(self.store.get(self.music_file))

    def test_selection_survives_reopening(self) -> None:
        decision = Decision("select", "spotify:track:example")
        self.store.save(self.music_file, decision)

        reopened = DecisionStore(self.database)

        self.assertEqual(reopened.get(self.music_file), decision)

    def test_skiip_can_replace_selection(self) -> None:
        self.store.save(self.music_file, Decision("select", "spotify:track:example"))
        self.store.save(self.music_file, Decision("skip"))

        self.assertEqual(self.store.get(self.music_file), Decision("skip"))

    def test_changed_file_invalidates_decision(self) -> None:
        self.store.save(self.music_file, Decision("skip"))

        # different size guarantees invalidation without timing assumptions
        self.music_file.write_bytes(b"changed audio content")

        self.assertIsNone(self.store.get(self.music_file))

    def test_forget_removes_decision(self) -> None:
        self.store.save(self.music_file, Decision("skip"))
        self.store.forget(self.music_file)

        self.assertIsNone(self.store.get(self.music_file))

    def test_selection_requires_track_uri(self) -> None:
        with self.assertRaises(ValueError):
            Decision("select")

        with self.assertRaises(ValueError):
            Decision("select", "spotify:album:example")

    def test_skip_cannot_include_track_uri(self) -> None:
        with self.assertRaises(ValueError):
            Decision("skip", "spotify:track:example")


if __name__ == "__main__":
    unittest.main()
