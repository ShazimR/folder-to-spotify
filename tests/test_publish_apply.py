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
    print_journal_status,
    reset_plan_with_urls,
    verify_plan,
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

    def test_verify_distinguishes_playlists_with_the_same_name(self) -> None:
        track_uri = "spotify:track:" + "T" * 22
        plan = LoadedPlan(
            root="/music",
            grouping="folders",
            playlists=[
                PlannedPlaylist(name="Billboard", track_uris=[track_uri]),
                PlannedPlaylist(name="Billboard", track_uris=[track_uri]),
            ],
        )
        fingerprint = plan_fingerprint(plan)
        ids = ["A" * 22, "B" * 22]

        for index, playlist_id in enumerate(ids):
            operation = f"playlist:{index}:create"
            self.journal.begin("account", fingerprint, operation)
            self.journal.complete(
                "account", fingerprint, operation, {"playlist_id": playlist_id}
            )

        self.spotify.current_user_saved_items.return_value = [False, True]

        with redirect_stdout(io.StringIO()) as output:
            verify_plan(self.spotify, self.journal, plan)

        report = output.getvalue()

        self.spotify.current_user_saved_items.assert_called_once_with(
            [f"spotify:playlist:{playlist_id}" for playlist_id in ids]
        )
        self.assertIn(
            f"1. Billboard: MISSING FROM LIBRARY\n"
            f"     https://open.spotify.com/playlist/{ids[0]}",
            report,
        )
        self.assertIn(
            f"2. Billboard: IN LIBRARY\n     https://open.spotify.com/playlist/{ids[1]}",
            report,
        )
        self.assertEqual(
            self.journal.lookup("account", fingerprint, "playlist:0:create"),
            (True, {"playlist_id": ids[0]}),
        )

    def test_reset_prints_recorded_url_once(self) -> None:
        fingerprint = plan_fingerprint(self.plan)
        operation = "playlist:0:create"
        self.journal.begin("account", fingerprint, operation)
        self.journal.complete(
            "account", fingerprint, operation, {"playlist_id": "original-id"}
        )

        with redirect_stdout(io.StringIO()) as first:
            removed = reset_plan_with_urls(
                self.journal, self.plan, "account", playlist_index=0
            )

        self.assertEqual(removed, 1)
        self.assertIn("https://open.spotify.com/playlist/original-id", first.getvalue())

        with redirect_stdout(io.StringIO()) as second:
            removed = reset_plan_with_urls(self.journal, self.plan, "account")

        self.assertEqual(removed, 0)
        self.assertEqual(second.getvalue(), "")

    def test_status_prints_playlist_url_once(self) -> None:
        fingerprint = plan_fingerprint(self.plan)
        for operation in ("playlist:0:create", "playlist:0:add:0"):
            self.journal.begin("account", fingerprint, operation)
            self.journal.complete(
                "account", fingerprint, operation, {"playlist_id": "original-id"}
            )

        with redirect_stdout(io.StringIO()) as output:
            print_journal_status(self.journal, self.plan, "account")

        report = output.getvalue()
        url = "https://open.spotify.com/playlist/original-id"
        self.assertIn(f"Create playlist: COMPLETE\n    {url}", report)
        self.assertEqual(report.count(url), 1)


if __name__ == "__main__":
    unittest.main()
