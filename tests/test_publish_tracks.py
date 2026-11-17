import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, call

from requests.exceptions import Timeout
from spotipy import Spotify

from folder_to_spotify.publish import PendingPublishError, ensure_tracks
from folder_to_spotify.publish_state import PublishJournal


class TrackPublishingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

        self.journal = PublishJournal(Path(self.directory.name) / "publish.sqlite3")
        self.spotify = Mock(spec=Spotify)
        self.spotify.playlist_add_items.return_value = {
            "snapshot_id": "snapshot",
        }

    def tracks(self, count: int) -> list[str]:
        return [f"spotify:track:{index:022d}" for index in range(count)]

    def ensure(self, tracks: list[str]) -> int:
        return ensure_tracks(
            self.spotify,
            self.journal,
            account_id="account",
            plan_hash="plan-hash",
            playlist_index=0,
            playlist_id="playlist-id",
            track_uris=tracks,
        )

    def test_batches_preserve_order(self) -> None:
        tracks = self.tracks(205)

        added = self.ensure(tracks)

        self.assertEqual(added, 205)
        self.assertEqual(
            self.spotify.playlist_add_items.call_args_list,
            [
                call(playlist_id="playlist-id", items=tracks[:100]),
                call(playlist_id="playlist-id", items=tracks[100:200]),
                call(playlist_id="playlist-id", items=tracks[200:]),
            ],
        )

    def test_exact_batch_size_sends_no_empty_request(self) -> None:
        tracks = self.tracks(100)

        self.assertEqual(self.ensure(tracks), 100)
        self.spotify.playlist_add_items.assert_called_once_with(
            playlist_id="playlist-id",
            items=tracks,
        )

    def test_completed_batches_are_not_repeated(self) -> None:
        tracks = self.tracks(150)
        self.ensure(tracks)
        self.spotify.reset_mock()

        self.assertEqual(self.ensure(tracks), 0)
        self.spotify.playlist_add_items.assert_not_called()

    def test_resumes_after_completed_batch(self) -> None:
        tracks = self.tracks(150)
        operation = "playlist:0:add:0"

        self.journal.begin("account", "plan-hash", operation)
        self.journal.complete(
            "account",
            "plan-hash",
            operation,
            {
                "playlist_id": "playlist-id",
                "track_uris": tracks[:100],
                "snapshot_id": "earlier-snapshot",
            },
        )

        self.assertEqual(self.ensure(tracks), 50)
        self.spotify.playlist_add_items.assert_called_once_with(
            playlist_id="playlist-id",
            items=tracks[100:],
        )

    def test_timeout_blocks_retry_and_later_batches(self) -> None:
        tracks = self.tracks(205)
        self.spotify.playlist_add_items.side_effect = [
            {"snapshot_id": "first-snapshot"},
            Timeout("Connection timed out"),
        ]

        with self.assertRaises(Timeout):
            self.ensure(tracks)

        self.assertEqual(
            self.journal.lookup("account", "plan-hash", "playlist:0:add:100"),
            (True, None),
        )
        self.assertEqual(
            self.journal.lookup("account", "plan-hash", "playlist:0:add:200"),
            (False, None),
        )

        self.spotify.reset_mock()

        with self.assertRaises(PendingPublishError):
            self.ensure(tracks)

        self.spotify.playlist_add_items.assert_not_called()

    def test_invalid_response_leaves_pending_operation(self) -> None:
        self.spotify.playlist_add_items.return_value = {}

        with self.assertRaises(ValueError):
            self.ensure(self.tracks(1))

        self.assertEqual(
            self.journal.lookup("account", "plan-hash", "playlist:0:add:0"),
            (True, None),
        )

    def test_saved_batch_must_match_request(self) -> None:
        self.ensure(self.tracks(1))
        self.spotify.reset_mock()

        # smulates a caller incorrectly reusing the same plan hash.
        with self.assertRaises(ValueError):
            self.ensure(self.tracks(2))

        self.spotify.playlist_add_items.assert_not_called()

    def test_empty_track_list_sends_no_requests(self) -> None:
        self.assertEqual(self.ensure([]), 0)
        self.spotify.playlist_add_items.assert_not_called()


if __name__ == "__main__":
    unittest.main()
