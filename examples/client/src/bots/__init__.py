"""Example Meyer clients built on the `maier.client` library: baseline bots
and an interactive human player, selectable from the command line."""

import argparse

from maier.client import run
from maier.client.types import OnMessage

BOTS = ["random", "honest", "minimal", "paranoid", "cutoff", "statistician", "human"]


def main() -> None:
    from bots import baselines, human

    parser = argparse.ArgumentParser(description="Run a Meyer baseline bot")
    parser.add_argument("bot", nargs="?", default="random", choices=BOTS)
    parser.add_argument("--name", help="display name (defaults to the bot kind)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.3,
        help="challenge threshold for cutoff/statistician",
    )
    parser.add_argument(
        "--start",
        action="store_true",
        help="ask the server to start the game as soon as this client has joined",
    )
    parser.add_argument(
        "--lobby",
        help="named lobby to join; created if it does not exist yet (server default otherwise)",
    )
    args = parser.parse_args()

    on_message: OnMessage | None = None
    interactive_start = False
    match args.bot:
        case "human":
            player = human.HumanPlayer()
            decide = player.decide
            on_message = player.on_message
            interactive_start = not args.start
        case "honest":
            decide = baselines.honest
        case "minimal":
            decide = baselines.minimal
        case "paranoid":
            decide = baselines.paranoid
        case "cutoff":
            decide = baselines.cutoff(args.threshold)
        case "statistician":
            decide = baselines.statistician(args.threshold)
        case _:
            decide = baselines.random_bot

    run(
        decide,
        args.name or args.bot,
        args.host,
        args.port,
        on_message=on_message,
        start=args.start,
        interactive_start=interactive_start,
        lobby=args.lobby,
    )
