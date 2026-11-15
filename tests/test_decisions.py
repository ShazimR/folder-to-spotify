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
        removed = self.store.forget(self.music_file)

        self.assertTrue(removed)
        self.assertIsNone(self.store.get(self.music_file))

    def test_forget_unknown_file_returns_false(self) -> None:
        self.assertFalse(self.store.forget(self.music_file))

    def test_forget_removes_stale_decision(self) -> None:
        self.store.save(self.music_file, Decision("skip"))
        self.music_file.write_bytes(b"changed audio content")

        self.assertIsNone(self.store.get(self.music_file))
        self.assertTrue(self.store.forget(self.music_file))
        self.assertFalse(self.store.forget(self.music_file))

    def test_forget_works_after_file_is_deleted(self) -> None:
        self.store.save(self.music_file, Decision("skip"))
        self.music_file.unlink()

        self.assertTrue(self.store.forget(self.music_file))

    def test_forget_many_removes_multiple_decisions(self) -> None:
        other = self.music_file.parent / "other.mp3"
        other.write_bytes(b"other audio")

        self.store.save(self.music_file, Decision("skip"))
        self.store.save(other, Decision("select", "spotify:track:example"))

        removed = self.store.forget_many([self.music_file, other])

        self.assertEqual(removed, 2)
        self.assertIsNone(self.store.get(self.music_file))
        self.assertIsNone(self.store.get(other))

    def test_forget_many_counts_only_existing_decisions(self) -> None:
        unknown = self.music_file.parent / "unknown"
        self.store.save(self.music_file, Decision("skip"))

        removed = self.store.forget_many([self.music_file, self.music_file, unknown])

        self.assertEqual(removed, 1)

    def test_forget_many_accepts_empty_input(self) -> None:
        self.assertEqual(self.store.forget_many([]), 0)

    def test_forget_many_preserves_unlisted_decisions(self) -> None:
        other = self.music_file.parent / "keep.mp3"
        other.write_bytes(b"keep this audio")

        self.store.save(self.music_file, Decision("skip"))
        self.store.save(other, Decision("skip"))

        self.store.forget_many([self.music_file])

        self.assertEqual(self.store.get(other), Decision("skip"))

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
