import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from folder_to_spotify.plan import LoadedPlan, PlannedPlaylist
from folder_to_spotify.publish_state import PublishJournal, plan_fingerprint


class PublishJournalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

        self.database = Path(self.directory.name) / "publish.sqlite3"
        self.journal = PublishJournal(self.database)
        self.key = ("account", "plan-hash", "playlist:0:create")

    def test_unknown_operation(self) -> None:
        self.assertEqual(self.journal.lookup(*self.key), (False, None))

    def test_pending_operation_survives_reopening(self) -> None:
        self.journal.begin(*self.key)

        reopened = PublishJournal(self.database)

        self.assertEqual(reopened.lookup(*self.key), (True, None))

    def test_completed_result_survives_reopening(self) -> None:
        result = {"playlist_id": "example"}
        self.journal.begin(*self.key)
        self.journal.complete(*self.key, result)

        reopened = PublishJournal(self.database)

        self.assertEqual(reopened.lookup(*self.key), (True, result))

    def test_cannot_begin_same_operation_twice(self) -> None:
        self.journal.begin(*self.key)

        with self.assertRaises(ValueError):
            self.journal.begin(*self.key)

    def test_cannot_complete_missing_operation(self) -> None:
        with self.assertRaises(ValueError):
            self.journal.complete(*self.key, {"playlist_id": "example"})

    def test_completed_result_cannot_be_overwritten(self) -> None:
        self.journal.begin(*self.key)
        self.journal.complete(*self.key, {"playlist_id": "original"})

        with self.assertRaises(ValueError):
            self.journal.complete(*self.key, {"playlist_id": "replacement"})

    def test_accounts_are_independent(self) -> None:
        self.journal.begin(*self.key)

        self.assertEqual(
            self.journal.lookup(
                "different-account",
                "plan-hash",
                "playlist:0:create",
            ),
            (False, None),
        )

    def test_reset_removes_creation_and_track_operations(self) -> None:
        self.journal.begin("account", "plan-hash", "playlist:0:create")
        self.journal.complete(
            "account",
            "plan-hash",
            "playlist:0:create",
            {"playlist_id": "example"},
        )
        self.journal.begin("account", "plan-hash", "playlist:0:add:0")

        removed = self.journal.reset_plan("account", "plan-hash")

        self.assertEqual(removed, 2)
        self.assertEqual(
            self.journal.lookup("account", "plan-hash", "playlist:0:create"),
            (False, None),
        )
        self.assertEqual(
            self.journal.lookup("account", "plan-hash", "playlist:0:add:0"),
            (False, None),
        )

    def test_reset_preserves_other_plans_and_accounts(self) -> None:
        operation = "playlist:0:create"

        self.journal.begin("account", "plan-hash", operation)
        self.journal.begin("account", "other-plan", operation)
        self.journal.begin("other-account", "plan-hash", operation)

        self.journal.reset_plan("account", "plan-hash")

        self.assertEqual(
            self.journal.lookup("account", "other-plan", operation),
            (True, None),
        )
        self.assertEqual(
            self.journal.lookup("other-account", "plan-hash", operation),
            (True, None),
        )

    def test_reset_unknown_plan_returns_zero(self) -> None:
        self.assertEqual(
            self.journal.reset_plan("account", "unknown-plan"),
            0,
        )

    def test_reset_allows_operation_to_begin_again(self) -> None:
        self.journal.begin(*self.key)
        self.journal.reset_plan("account", "plan-hash")

        self.journal.begin(*self.key)

        self.assertEqual(
            self.journal.lookup(*self.key),
            (True, None),
        )

    def test_reset_one_playlist_preserves_similarly_numbered_playlist(self) -> None:
        account = "account-a"
        plan = "plan-a"
        target = ["playlist:1:create", "playlist:1:add:0", "playlist:1:add:100"]
        neighbor = "playlist:10:create"

        for operation in [*target, neighbor]:
            self.journal.begin(account, plan, operation)

        removed = self.journal.reset_plan(account, plan, playlist_index=1)

        self.assertEqual(removed, 3)
        for operation in target:
            self.assertEqual(
                self.journal.lookup(account, plan, operation),
                (False, None),
            )
        self.assertEqual(self.journal.lookup(account, plan, neighbor), (True, None))
        self.assertEqual(self.journal.reset_plan(account, plan, playlist_index=1), 0)


class PlanFingerprintTests(unittest.TestCase):
    def make_plan(self, root: str, uris: list[str]) -> LoadedPlan:
        return LoadedPlan(
            root=root,
            grouping="single",
            playlists=[
                PlannedPlaylist(name="Favorites", track_uris=uris),
            ],
        )

    def test_root_location_does_not_change_fingerprint(self) -> None:
        first = self.make_plan("/music", ["spotify:track:one"])
        moved = self.make_plan("/new/music", ["spotify:track:one"])

        self.assertEqual(plan_fingerprint(first), plan_fingerprint(moved))

    def test_track_order_changes_fingerprint(self) -> None:
        first = self.make_plan(
            "/music",
            ["spotify:track:one", "spotify:track:two"],
        )
        reversed_plan = self.make_plan(
            "/music",
            ["spotify:track:two", "spotify:track:one"],
        )

        self.assertNotEqual(
            plan_fingerprint(first),
            plan_fingerprint(reversed_plan),
        )


if __name__ == "__main__":
    unittest.main()
