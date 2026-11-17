import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from folder_to_spotify.plan import PlaylistPlan, load_plan

URI_ONE = "spotify:track:" + "A" * 22
URI_TWO = "spotify:track:" + "B" * 22


class PlanLoadingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = Path(self.directory.name) / "plan.json"

    def write_plan(self, data: object) -> None:
        self.source.write_text(
            json.dumps(data),
            encoding="utf-8",
        )

    def valid_data(self) -> dict:
        return {
            "version": 1,
            "root": "/music",
            "grouping": "folders",
            "playlists": [
                {
                    "name": "1966",
                    "track_uris": [URI_TWO, URI_ONE],
                }
            ],
        }

    def test_load_preserves_track_order(self) -> None:
        self.write_plan(self.valid_data())

        loaded = load_plan(self.source)

        self.assertEqual(loaded.root, "/music")
        self.assertEqual(loaded.grouping, "folders")
        self.assertEqual(loaded.playlists[0].name, "1966")
        self.assertEqual(
            loaded.playlists[0].track_uris,
            [URI_TWO, URI_ONE],
        )

    def test_exported_plan_can_be_loaded(self) -> None:
        root = Path(self.directory.name) / "Music"
        plan = PlaylistPlan(root, grouping="folders")
        plan.add(root / "1966" / "song.mp3", URI_ONE)
        plan.save(self.source)

        loaded = load_plan(self.source)

        self.assertEqual(loaded.root, str(root.resolve()))
        self.assertEqual(loaded.playlists[0].track_uris, [URI_ONE])

    def test_rejects_invalid_top_level_fields(self) -> None:
        cases = [
            ("version", True),
            ("version", 2),
            ("root", ""),
            ("root", 123),
            ("grouping", "unknown"),
            ("playlists", {}),
        ]

        for field, value in cases:
            with self.subTest(field=field, value=value):
                data = self.valid_data()
                data[field] = value
                self.write_plan(data)

                with self.assertRaises(ValueError):
                    load_plan(self.source)

    def test_rejects_invalid_playlist_entries(self) -> None:
        entries = [
            "not an object",
            {"name": "", "track_uris": [URI_ONE]},
            {"name": "1966", "track_uris": URI_ONE},
            {"name": "1966", "track_uris": []},
            {"name": "1966", "track_uris": ["spotify:track:bad"]},
            {"name": "1966", "track_uris": [None]},
            {"name": "1966", "track_uris": [URI_ONE, URI_ONE]},
        ]

        for entry in entries:
            with self.subTest(entry=entry):
                data = self.valid_data()
                data["playlists"] = [entry]
                self.write_plan(data)

                with self.assertRaises(ValueError):
                    load_plan(self.source)

    def test_same_track_allowed_in_different_playlists(self) -> None:
        data = self.valid_data()
        data["playlists"] = [
            {"name": "1966", "track_uris": [URI_ONE]},
            {"name": "Favorites", "track_uris": [URI_ONE]},
        ]
        self.write_plan(data)

        loaded = load_plan(self.source)

        self.assertEqual(len(loaded.playlists), 2)

    def test_single_grouping_rejects_multiple_playlists(self) -> None:
        data = self.valid_data()
        data["grouping"] = "single"
        data["playlists"] *= 2
        self.write_plan(data)

        with self.assertRaises(ValueError):
            load_plan(self.source)

    def test_empty_plan_is_valid(self) -> None:
        data = self.valid_data()
        data["playlists"] = []
        self.write_plan(data)

        self.assertEqual(load_plan(self.source).playlists, [])

    def test_rejects_non_object_json(self) -> None:
        self.write_plan([])

        with self.assertRaises(ValueError):
            load_plan(self.source)

    def test_rejects_malformed_json(self) -> None:
        self.source.write_text("{broken", encoding="utf-8")

        with self.assertRaises(ValueError):
            load_plan(self.source)


if __name__ == "__main__":
    unittest.main()
