import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from folder_to_spotify.search_cache import (
    FALLBACK_COOLDOWN_SECONDS,
    SearchCache,
    SearchPaused,
)


class SearchCacheTests(unittest.TestCase):
    def test_legacy_cooldown_expires_from_original_save_time(self) -> None:
        with (
            TemporaryDirectory() as directory,
            patch.object(Path, "home", return_value=Path(directory)),
            patch("folder_to_spotify.search_cache.time.time") as clock,
        ):
            saved_at = 1_700_000_000
            clock.return_value = saved_at
            SearchCache()._write("cooldown", {"until": None, "reason": "HTTP 429"})

            deadline = saved_at + FALLBACK_COOLDOWN_SECONDS
            clock.return_value = deadline - 1
            with self.assertRaises(SearchPaused):
                SearchCache()._check_cooldown()

            clock.return_value = deadline
            SearchCache()._check_cooldown()


if __name__ == "__main__":
    unittest.main()
