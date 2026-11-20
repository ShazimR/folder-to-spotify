# Folder to Spotify

Turn a local music collection into private Spotify playlists. The CLI reads metadata from your files, finds tracks in Spotify’s catalog, and lets you review uncertain matches before publishing. Your audio stays on disk. Each playlist entry points to a Spotify catalog track.

## Installation

Use Python 3.11 or newer. From a Bash shell, run:

```bash
git clone https://github.com/ShazimR/folder-to-spotify.git
cd folder-to-spotify
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
folder-to-spotify --help
```

You can try the scanner before connecting Spotify. Set `music` to the folder containing your songs. For example:

```bash
music="$HOME/Music"
folder-to-spotify scan "$music"
```

The scanner walks subdirectories and reports each readable file’s title, artist, album, and duration. If the title tag is missing, it uses the filename without its extension. It looks for MP3, MP4, M4A, FLAC, WAV, OGG, Opus, AAC, AIFF/AIF, and WMA files and reports any metadata read failures.

## Connect Spotify

1. Create an app in the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) and select **Web API**. The owner of a Development Mode app needs an active Spotify Premium subscription. [Spotify’s Development Mode requirements](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide)
2. In the app settings, register this exact redirect URI: `http://127.0.0.1:8888/callback`.
3. Copy the app’s **Client ID** and run the commands below. The CLI uses OAuth with PKCE, so the Client ID is the only app credential you need to configure.

```bash
export SPOTIPY_CLIENT_ID="your-client-id"
folder-to-spotify auth
```

Open the authorization URL printed in the terminal. After approving access, copy the **entire redirected URL** from your browser’s address bar and paste it into the terminal. With this manual flow, the browser may show a connection error on the callback page. The URL in the address bar is what the CLI needs.

Keep `SPOTIPY_CLIENT_ID` exported in shells where you run searches or access Spotify.

## Publish your first playlist

Start with ten readable files. Run this in an interactive terminal using the `music` directory set above.

```bash
mkdir -p .tmp
plan=".tmp/first-playlist.json"

folder-to-spotify search "$music" \
    --limit 10 \
    --match-mode song \
    --review \
    --plan-out "$plan"
```

The plan includes automatic matches and your manual selections. When a song needs review, the CLI displays the candidates, album names, durations, scores, and Spotify links.

| At the review prompt | Action |
| --- | --- |
| Candidate number | Select that Spotify track and remember the choice. |
| `s` | Skip the file and remember the choice. |
| Enter | Leave the file unresolved so you can revisit it later. |
| `q` | End the run. Earlier decisions are saved, and the partial plan is not exported. |

Preview the playlist names and track counts locally:

```bash
folder-to-spotify publish "$plan"
```

When you’re ready, publish the plan and check that the playlists are in your Spotify library:

```bash
folder-to-spotify publish "$plan" --apply
folder-to-spotify publish "$plan" --verify
```

Publishing prints the Spotify account ID, playlist URLs, and number of tracks added. Applying the same completed plan again for the same account reuses the recorded playlists and track batches.

## Matching and folder grouping

| Search option | Behavior |
| --- | --- |
| `--match-mode strict` | Default. Requires an exact normalized title and artist, a duration within three seconds, and a clear lead over competing recordings. |
| `--match-mode song` | Accepts compatible releases such as a remaster while preserving version labels such as “live” and “acoustic”. Among eligible releases, prefers album similarity, then the closest duration. |
| `--grouping single` | Default. Combines selected tracks into one playlist named after the root directory. |
| `--grouping folders` | Creates a playlist for each immediate subfolder with selected tracks. Files deeper in the tree belong to that subfolder’s playlist. Files directly under the root go into a playlist named after the root. |
| `--limit N` | Processes up to N readable files, including files with saved decisions. The default is 5. |
| `--plan-out PATH` | Exports the selections to a new JSON file. The parent directory must exist. Choose a fresh filename for each export. |

For example, if `Billboard` is the root and you use `--grouping folders`, `Billboard/1970/Disc 1/song.mp3` goes into the **1970** playlist. Each Spotify track URI appears once per destination playlist, in first-selected order. The same track can appear in multiple playlists.

Each search considers up to five Spotify candidates. Both match modes send filename-derived titles and missing artists to review when candidates exist. An **unmatched** result means the query returned no candidates.

The CLI reuses a saved selection or skip while the file’s path, size, and modification time match. To reconsider a file on the next run:

```bash
folder-to-spotify decisions forget "$music/1970/song.mp3"
```

`decisions forget` also accepts multiple file paths in one command.

## Cached searches and rate limits

Online searches reuse cached results for seven days. After an online run, you can compare match modes or review cached candidates offline:

```bash
folder-to-spotify search "$music" --offline --limit 100 --match-mode song --review
```

Offline mode can use expired entries and reports **cache misses** separately from unmatched songs. Use the same `SPOTIPY_CLIENT_ID` that populated the cache.

If Spotify rate-limits a search, completed queries stay cached. When Spotify supplies a retry time, the CLI records the cooldown and reports when online searches can resume.

## Check or recreate a published playlist

Set `account` to the Spotify account ID printed by `--apply` or `--verify`.

```bash
account="your-spotify-account-id"
folder-to-spotify publish "$plan" --status --account-id "$account"
folder-to-spotify publish "$plan" --verify
```

| Command | What it checks |
| --- | --- |
| `--status` | Reads the local publish journal. Shows playlist creation and track batches as `NEVER ATTEMPTED`, `PENDING`, or `COMPLETE`, with the recorded playlist URL when available. Works offline. |
| `--verify` | Checks whether each recorded playlist ID is in the signed-in user’s Spotify library. It checks membership only. `NO CREATION RECORD` means the journal has no saved ID for that playlist. |

If you remove a playlist from your Spotify library, its journal status can still say `COMPLETE` while verification says `MISSING FROM LIBRARY`. To recreate **only playlist 2** in a multi-playlist plan, confirm its number and URL in the report, then run:

```bash
folder-to-spotify publish "$plan" --reset-journal --playlist 2 --account-id "$account"
folder-to-spotify publish "$plan" --apply
```

Reset prints the previously recorded URL and clears local publish history for that playlist. The next apply creates a fresh playlist. If the original is still in your library, you’ll have both copies. Omitting `--playlist` resets every playlist in that plan for the specified account.

The journal identifies a plan by its ordered playlist names and track URIs. Changing a name, track list, or order produces a **new publication**. If a network interruption leaves a write `PENDING`, inspect the playlist in Spotify before resetting. Spotify may already have accepted the write.

## Development

Install the development dependencies and run the project checks:

```bash
python -m pip install -e '.[dev]'
bash scripts/check.sh
```

The script runs Ruff linting and formatting checks, mypy, and the unittest suite. Use `folder-to-spotify COMMAND --help` to see the options for any command.

## Contributing

Issues and pull requests are welcome. If you find a bug or have a feature idea,
[open an issue](https://github.com/ShazimR/folder-to-spotify/issues).
For song-matching issues, include the match mode, the local track metadata,
and which Spotify candidate you expected the CLI to select.

To contribute a change, fork the repository, make your changes on a branch,
and run `bash scripts/check.sh`. Open a pull request against `main` describing
what changed and how you tested it. I review pull requests before merging.

## License

This project is licensed under the [MIT License](LICENSE).
