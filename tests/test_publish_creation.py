import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from requests.exceptions import Timeout
from spotipy import Spotify

from folder_to_spotify.publish import (
    PendingPublishError,
    ensure_playlist,
)
from folder_to_spotify.publish_state import PublishJournal


class PlaylistCreationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

        self.journal = PublishJournal(Path(self.directory.name) / "publish.sqlite3")
        self.spotify = Mock(spec=Spotify)
        self.spotify.current_user_playlist_create.return_value = {
            "id": "created-playlist",
        }

    def ensure(self) -> str:
        return ensure_playlist(
            self.spotify,
            self.journal,
            account_id="account",
            plan_hash="plan-hash",
            playlist_index=0,
            name="1966",
        )

    def test_creates_private_playlist_and_records_id(self) -> None:
        playlist_id = self.ensure()

        self.assertEqual(playlist_id, "created-playlist")
        self.spotify.current_user_playlist_create.assert_called_once_with(
            name="1966",
            public=False,
            description="Created with folder-to-spotify",
        )
        self.assertEqual(
            self.journal.lookup("account", "plan-hash", "playlist:0:create"),
            (True, {"playlist_id": "created-playlist"}),
        )

    def test_completed_creation_is_not_repeated(self) -> None:
        first = self.ensure()
        second = self.ensure()

        self.assertEqual(first, second)
        self.spotify.current_user_playlist_create.assert_called_once()

    def test_pending_creation_blocks_request(self) -> None:
        self.journal.begin("account", "plan-hash", "playlist:0:create")

        with self.assertRaises(PendingPublishError):
            self.ensure()

        self.spotify.current_user_playlist_create.assert_not_called()

    def test_timeout_leaves_pending_operation(self) -> None:
        self.spotify.current_user_playlist_create.side_effect = Timeout(
            "Connection timed out"
        )

        with self.assertRaises(Timeout):
            self.ensure()

        self.assertEqual(
            self.journal.lookup("account", "plan-hash", "playlist:0:create"),
            (True, None),
        )

        # a later attempt must not repeat the creation request.
        with self.assertRaises(PendingPublishError):
            self.ensure()

        self.spotify.current_user_playlist_create.assert_called_once()

    def test_invalid_response_leaves_pending_operation(self) -> None:
        self.spotify.current_user_playlist_create.return_value = {}

        with self.assertRaises(ValueError):
            self.ensure()

        self.assertEqual(
            self.journal.lookup("account", "plan-hash", "playlist:0:create"),
            (True, None),
        )


if __name__ == "__main__":
    unittest.main()
