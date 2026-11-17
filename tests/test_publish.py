import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from folder_to_spotify.plan import LoadedPlan, PlannedPlaylist
from folder_to_spotify.publish import describe_plan, main


class PublishPreviewTests(unittest.TestCase):
    def test_describes_multiple_playlists(self) -> None:
        plan = LoadedPlan(
            root="/music",
            grouping="folders",
            playlists=[
                PlannedPlaylist(
                    name="1966",
                    track_uris=["spotify:track:" + "A" * 22],
                ),
                PlannedPlaylist(
                    name="1970",
                    track_uris=[
                        "spotify:track:" + "B" * 22,
                        "spotify:track:" + "C" * 22,
                    ],
                ),
            ],
        )

        summary = describe_plan(plan)

        self.assertIn("Playlists: 2", summary)
        self.assertIn("Track placements: 3", summary)
        self.assertIn("1. 1966: 1 tracks", summary)
        self.assertIn("2. 1970: 2 tracks", summary)

    def test_empty_plan_reports_nothing_to_publish(self) -> None:
        plan = LoadedPlan(
            root="/music",
            grouping="single",
            playlists=[],
        )
        output = io.StringIO()

        with (
            patch("sys.argv", ["publish", "plan.json"]),
            patch(
                "folder_to_spotify.publish.load_plan",
                return_value=plan,
            ),
            redirect_stdout(output),
        ):
            main()

        self.assertIn("Nothing to publish", output.getvalue())

    def test_invalid_plan_exits_with_readable_error(self) -> None:
        errors = io.StringIO()

        with (
            patch("sys.argv", ["publish", "plan.json"]),
            patch(
                "folder_to_spotify.publish.load_plan",
                side_effect=ValueError("Unsupported plan version"),
            ),
            redirect_stderr(errors),
            self.assertRaises(SystemExit) as raised,
        ):
            main()

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("Unsupported plan version", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
