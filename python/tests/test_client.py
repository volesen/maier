"""End-to-end test of the `client` library against the server: two bots built
exactly the way the docs describe, playing a full game."""

import random
import socket
import threading

from maier.client import run
from maier.client.types import Action, GameEnd, ServerMessage, State, Welcome
from maier.server.game import serve


def test_run_plays_a_full_game() -> None:
    with socket.create_server(("127.0.0.1", 0)) as listener:
        port = listener.getsockname()[1]
        threading.Thread(target=serve, args=(listener, 5.0, 7), daemon=True).start()

        winners: dict[str, str] = {}
        first_joined = threading.Event()

        def bot(name: str, seed: int, start: bool) -> None:
            rng = random.Random(seed)

            def decide(state: State, legal: list[Action]) -> Action:
                return rng.choice(legal)

            def on_message(msg: ServerMessage) -> None:
                if isinstance(msg, Welcome):
                    first_joined.set()
                if isinstance(msg, GameEnd):
                    winners[name] = msg.winner

            run(decide, name, port=port, on_message=on_message, start=start)

        first = threading.Thread(target=bot, args=("a", 1, False), daemon=True)
        first.start()
        # The starter must join last: a start in a one-player lobby is ignored.
        assert first_joined.wait(timeout=5), "first bot never joined"
        second = threading.Thread(target=bot, args=("b", 2, True), daemon=True)
        second.start()

        for thread in (first, second):
            thread.join(timeout=15)
            assert not thread.is_alive(), "bot did not finish"

        assert winners["a"] == winners["b"]
        assert winners["a"] in {"p0", "p1"}
