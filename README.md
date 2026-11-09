# Folder to Spotify

A Python CLI that scans local music folders, matches songs to Spotify's
catalog, and adds the matches to playlists.

## Planned features

- Recursively scan local music folders.
- Extract title, artist, album, and duration from metadata.
- Fall back to filenames when metadata is missing.
- Report ambiguous matches and songs unavailable on Spotify.
- Skip duplicate tracks within each destination playlist.
- Create one combined playlist or separate playlists by folder.

This tool adds Spotify catalog tracks; it does not upload audio files.

## Status

Initial setup. Import functionality is not implemented yet.
