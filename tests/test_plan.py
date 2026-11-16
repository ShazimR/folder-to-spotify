import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from folder_to_spotify.plan import PlaylistPlan


class PlaylistPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

        self.root = Path(self.directory.name) / "Music"
        self.root.mkdir()

    def test_single_mode_combines_folders(self) -> None:
        plan = PlaylistPlan(self.root)

        plan.add(self.root / "1966" / "one.mp3", "spotify:track:one")
        plan.add(self.root / "1967" / "two.mp3", "spotify:track:two")

        self.assertEqual(len(plan.playlists), 1)
        self.assertEqual(plan.playlists[0].name, "Music")
        self.assertEqual(
            plan.playlists[0].track_uris,
            ["spotify:track:one", "spotify:track:two"],
        )

    def test_folder_mode_groups_nested_files(self) -> None:
        plan = PlaylistPlan(self.root, grouping="folders")

        plan.add(self.root / "1966" / "one.mp3", "spotify:track:one")
        plan.add(
            self.root / "1966" / "Disc 2" / "two.mp3",
            "spotify:track:two",
        )
        plan.add(self.root / "1967" / "three.mp3", "spotify:track:three")

        playlists = {playlist.name: playlist.track_uris for playlist in plan.playlists}

        self.assertEqual(
            playlists,
            {
                "1966": ["spotify:track:one", "spotify:track:two"],
                "1967": ["spotify:track:three"],
            },
        )

    def test_root_files_have_their_own_playlist(self) -> None:
        plan = PlaylistPlan(self.root, grouping="folders")

        plan.add(self.root / "one.mp3", "spotify:track:one")
        plan.add(self.root / "1966" / "two.mp3", "spotify:track:two")

        self.assertEqual(
            [playlist.name for playlist in plan.playlists],
            ["Music", "1966"],
        )

    def test_duplicates_are_removed_within_playlist(self) -> None:
        plan = PlaylistPlan(self.root)

        first = plan.add(self.root / "one.mp3", "spotify:track:one")
        duplicate = plan.add(
            self.root / "copy.mp3",
            "spotify:track:one",
        )

        self.assertTrue(first)
        self.assertFalse(duplicate)
        self.assertEqual(
            plan.playlists[0].track_uris,
            ["spotify:track:one"],
        )

    def test_same_track_can_appear_in_different_playlists(self) -> None:
        plan = PlaylistPlan(self.root, grouping="folders")

        self.assertTrue(plan.add(self.root / "1966" / "one.mp3", "spotify:track:one"))
        self.assertTrue(
            plan.add(self.root / "Favorites" / "one.mp3", "spotify:track:one")
        )

        self.assertEqual(len(plan.playlists), 2)

    def test_outside_root_is_rejected(self) -> None:
        plan = PlaylistPlan(self.root)

        with self.assertRaises(ValueError):
            plan.add(
                self.root.parent / "outside.mp3",
                "spotify:track:one",
            )

        self.assertEqual(plan.playlists, [])

    def test_invalid_uri_is_rejected(self) -> None:
        plan = PlaylistPlan(self.root)

        for uri in ("", "spotify:album:one", "spotify:track:"):
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                plan.add(self.root / "one.mp3", uri)

    def test_empty_plan_has_no_playlists(self) -> None:
        plan = PlaylistPlan(self.root)

        self.assertEqual(plan.playlists, [])

    def test_export_contains_grouped_deduplicated_tracks(self) -> None:
        plan = PlaylistPlan(self.root, grouping="folders")
        plan.add(self.root / "1966" / "one.mp3", "spotify:track:one")
        plan.add(self.root / "1966" / "copy.mp3", "spotify:track:one")

        self.assertEqual(
            plan.to_dict(),
            {
                "version": 1,
                "root": str(self.root.resolve()),
                "grouping": "folders",
                "playlists": [
                    {
                        "name": "1966",
                        "track_uris": ["spotify:track:one"],
                    }
                ],
            },
        )

    def test_save_writes_readable_json(self) -> None:
        plan = PlaylistPlan(self.root, grouping="folders")
        plan.add(self.root / "Café" / "one.mp3", "spotify:track:one")
        destination = self.root / "plan.json"

        plan.save(destination)

        content = destination.read_text(encoding="utf-8")
        self.assertEqual(json.loads(content), plan.to_dict())
        self.assertIn("Café", content)
        self.assertTrue(content.endswith("\n"))

    def test_save_preserves_existing_file(self) -> None:
        plan = PlaylistPlan(self.root)
        destination = self.root / "plan.json"
        destination.write_text("existing content", encoding="utf-8")

        with self.assertRaises(FileExistsError):
            plan.save(destination)

        self.assertEqual(
            destination.read_text(encoding="utf-8"),
            "existing content",
        )

    def test_empty_plan_exports_empty_playlist_list(self) -> None:
        plan = PlaylistPlan(self.root)
        destination = self.root / "empty-plan.json"

        plan.save(destination)


if __name__ == "__main__":
    unittest.main()
