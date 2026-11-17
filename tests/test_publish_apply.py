import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from spotipy import Spotify

from folder_to_spotify.plan import LoadedPlan, PlannedPlaylist
from folder_to_spotify.publish import (
    PendingPublishError,
    apply_plan,
    main,
)
from folder_to_spotify.publish_state import PublishJournal, plan_fingerprint


class ApplyPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

        self.journal = PublishJournal(Path(self.directory.name) / "publish.sqlite3")
        self.plan = LoadedPlan(
            root="/music",
            grouping="single",
            playlists=[
                PlannedPlaylist(
                    name="Favorites",
                    track_uris=["spotify:track:" + "A" * 22],
                )
            ],
        )

        self.spotify = Mock(spec=Spotify)
        self.spotify.current_user.return_value = {"id": "account"}
        self.spotify.current_user_playlist_create.return_value = {"id": "playlist-id"}
        self.spotify.playlist_add_items.return_value = {"snapshot_id": "snapshot"}

    def test_publishes_and_reuses_completed_operations(self) -> None:
        with redirect_stdout(io.StringIO()):
            first = apply_plan(self.spotify, self.journal, self.plan)
            second = apply_plan(self.spotify, self.journal, self.plan)

        self.assertEqual(first, 1)
        self.assertEqual(second, 0)
        self.spotify.current_user_playlist_create.assert_called_once()
        self.spotify.playlist_add_items.assert_called_once_with(
            playlist_id="playlist-id",
            items=self.plan.playlists[0].track_uris,
        )

    def test_invalid_account_prevents_writes(self) -> None:
        self.spotify.current_user.return_value = {}

        with self.assertRaises(ValueError):
            apply_plan(self.spotify, self.journal, self.plan)

        self.spotify.current_user_playlist_create.assert_not_called()
        self.spotify.playlist_add_items.assert_not_called()

    def test_pending_creation_prevents_track_addition(self) -> None:
        self.journal.begin(
            "account",
            plan_fingerprint(self.plan),
            "playlist:0:create",
        )

        with (
            redirect_stdout(io.StringIO()),
            self.assertRaises(PendingPublishError),
        ):
            apply_plan(self.spotify, self.journal, self.plan)

        self.spotify.current_user_playlist_create.assert_not_called()
        self.spotify.playlist_add_items.assert_not_called()

    def test_preview_does_not_authenticate_or_open_journal(self) -> None:
        with (
            patch("sys.argv", ["publish", "plan.json"]),
            patch(
                "folder_to_spotify.publish.load_plan",
                return_value=self.plan,
            ),
            patch("folder_to_spotify.publish.get_spotify_client") as get_client,
            patch("folder_to_spotify.publish.PublishJournal") as journal_class,
            redirect_stdout(io.StringIO()),
        ):
            main()

        get_client.assert_not_called()
        journal_class.assert_not_called()

    def test_apply_flag_calls_publisher(self) -> None:
        with (
            patch("sys.argv", ["publish", "plan.json", "--apply"]),
            patch(
                "folder_to_spotify.publish.load_plan",
                return_value=self.plan,
            ),
            patch(
                "folder_to_spotify.publish.get_spotify_client",
                return_value=self.spotify,
            ),
            patch(
                "folder_to_spotify.publish.PublishJournal",
                return_value=self.journal,
            ),
            patch(
                "folder_to_spotify.publish.apply_plan",
                return_value=1,
            ) as publish,
            redirect_stdout(io.StringIO()),
        ):
            main()

        publish.assert_called_once_with(
            self.spotify,
            self.journal,
            self.plan,
        )


if __name__ == "__main__":
    unittest.main()
