import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from folder_to_spotify.__main__ import main


class CliTests(unittest.TestCase):
    def test_publish_receives_its_arguments(self) -> None:
        with patch("folder_to_spotify.__main__.publish.main") as publish:
            main(["publish", "plan.json", "--status", "--account-id", "account"])

        publish.assert_called_once_with(
            ["plan.json", "--status", "--account-id", "account"],
            prog="folder-to-spotify publish",
        )

    def test_bare_folder_still_scans(self) -> None:
        with patch("folder_to_spotify.__main__.cli.main") as scan:
            main(["/mnt/d/BillBoard"])

        scan.assert_called_once_with(["/mnt/d/BillBoard"], prog="folder-to-spotify")

    def test_auth_help_does_not_start_login(self) -> None:
        with (
            patch("folder_to_spotify.__main__.auth.main") as login,
            redirect_stdout(io.StringIO()) as output,
            self.assertRaises(SystemExit) as exit_status,
        ):
            main(["auth", "--help"])

        self.assertEqual(exit_status.exception.code, 0)
        self.assertIn("folder-to-spotify auth", output.getvalue())
        login.assert_not_called()
