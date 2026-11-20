import argparse
import sys

from folder_to_spotify import auth, cli, decisions, publish, search


def main(argv: list[str] | None = None, *, prog: str | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(
        prog="folder-to-spotify",
        description="Build Spotify playlists from local music folders.",
        epilog="Run folder-to-spotify COMMAND --help for command options.",
    )
    commands = {
        "scan": cli.main,
        "search": search.main,
        "publish": publish.main,
        "decisions": decisions.main,
    }
    parser.add_argument(
        "command",
        choices=["scan", "auth", "search", "publish", "decisions"],
        help="Choose a step in the playlist workflow",
    )

    if not args:
        parser.print_help()
        return

    # preserve the original `folder-to-spotify PATH` scanner invocation.
    first = args[0]
    if first == "--" or (
        not first.startswith("-") and first not in commands and first != "auth"
    ):
        cli.main(args, prog=parser.prog)
        return

    command = parser.parse_args(args[:1]).command
    command_prog = f"{parser.prog} {command}"

    if command == "auth":
        # parse help and reject extra arguments before starting OAuth.
        auth_parser = argparse.ArgumentParser(
            prog=command_prog,
            description="Connect your Spotify account.",
        )
        auth_parser.parse_args(args[1:])
        auth.main()
        return

    commands[command](args[1:], prog=command_prog)


if __name__ == "__main__":
    main()
