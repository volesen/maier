"""Minimal Meyer bot client: implement decide(state, legal) -> action and call run()."""

import argparse
import json
import socket

from pydantic import TypeAdapter

from client.types import Decide, EventBase, GameEnd, OnEvent, ServerMessage, Turn

_server_message = TypeAdapter[ServerMessage](ServerMessage)

BOTS = ["random", "honest", "minimal", "paranoid", "cutoff", "statistician"]


def run(
    decide: Decide,
    name: str,
    host: str = "127.0.0.1",
    port: int = 5000,
    on_event: OnEvent | None = None,
) -> None:
    with socket.create_connection((host, port)) as sock:
        f = sock.makefile("rw", encoding="utf-8", newline="\n")

        def send(obj: dict) -> None:
            f.write(json.dumps(obj) + "\n")
            f.flush()

        send({"type": "join", "name": name, "protocol": 1})
        for line in f:
            msg = _server_message.validate_json(line)
            match msg:
                case Turn():
                    action = decide(msg.state, msg.legal_actions)
                    send(
                        {
                            "type": "act",
                            "request_id": msg.request_id,
                            "action": action.model_dump(),
                        }
                    )
                case GameEnd():
                    print(line, end="")
                    return
                case EventBase() if on_event is not None:
                    print(line, end="")
                    on_event(msg)
                case _:
                    print(line, end="")


def main() -> None:
    from client import baselines

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
    args = parser.parse_args()

    match args.bot:
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

    run(decide, args.name or args.bot, args.host, args.port)
