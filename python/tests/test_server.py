"""Integration test: run the server's game loop against bot clients over
socket pairs, checking the wire protocol end to end."""

import json
import random
import socket
import threading
import time

import pytest
from pydantic import BaseModel

from server import protocol as proto
from server.game import Client, Game, LineReader, wait_for_players


class BotResult(BaseModel):
    events: list[str]
    winner: str | None


def _run_bot(sock: socket.socket, rng_seed: int, result: BotResult) -> None:
    """Picks a random legal action every turn until the game ends."""
    rng = random.Random(rng_seed)
    reader = LineReader(sock)

    def send(msg: dict[str, object]) -> None:
        sock.sendall((json.dumps(msg) + "\n").encode())

    while True:
        line = reader.read_line(deadline=time.monotonic() + 10)
        assert line is not None, "server went silent"
        msg = proto.server_message_adapter.validate_python(json.loads(line))
        result.events.append(msg.type)
        match msg:
            case proto.Turn():
                action = rng.choice(msg.legal_actions)
                send(
                    {
                        "type": "act",
                        "request_id": msg.request_id,
                        "action": action.model_dump(mode="json"),
                    }
                )
            case proto.GameEnd():
                result.winner = msg.winner
                return
            case _:
                pass


@pytest.mark.parametrize("seed", range(5))
def test_full_game_over_sockets(seed: int) -> None:
    num_players = 3
    clients: list[Client] = []
    bot_socks: list[socket.socket] = []
    for i in range(num_players):
        server_side, bot_side = socket.socketpair()
        clients.append(Client(player_id=f"p{i}", name=f"bot{i}", sock=server_side))
        bot_socks.append(bot_side)

    results = [BotResult(events=[], winner=None) for _ in range(num_players)]
    threads = [
        threading.Thread(target=_run_bot, args=(sock, seed * 100 + i, results[i]), daemon=True)
        for i, sock in enumerate(bot_socks)
    ]
    for thread in threads:
        thread.start()

    Game(clients, turn_deadline_s=5.0, dice_seed=seed).run()

    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive(), "bot did not finish"

    winners = {result.winner for result in results}
    assert len(winners) == 1, "all bots must agree on the winner"
    winner = winners.pop()
    assert winner in {f"p{i}" for i in range(num_players)}
    for result in results:
        # Every client saw the game start, at least one round, and the end.
        assert result.events[0] == "game_start"
        assert "round_start" in result.events
        assert result.events[-1] == "game_end"

    for sock in bot_socks:
        sock.close()
    for client in clients:
        client.sock.close()


def test_lobby_starts_on_start_message() -> None:
    with socket.create_server(("127.0.0.1", 0)) as listener:
        port = listener.getsockname()[1]
        result: list[Client] = []

        def lobby() -> None:
            result.extend(wait_for_players(listener))

        thread = threading.Thread(target=lobby, daemon=True)
        thread.start()

        def join(name: str) -> socket.socket:
            sock = socket.create_connection(("127.0.0.1", port), timeout=5)
            sock.sendall((json.dumps({"type": "join", "name": name}) + "\n").encode())
            reader = LineReader(sock)
            line = reader.read_line(time.monotonic() + 5)
            assert line is not None
            welcome = proto.server_message_adapter.validate_python(json.loads(line))
            assert isinstance(welcome, proto.Welcome)
            return sock

        first = join("first")
        # A start with only one player joined must be ignored.
        first.sendall(b'{"type": "start"}\n')
        time.sleep(0.2)
        assert thread.is_alive(), "lobby must not start with a single player"

        second = join("second")
        third = join("third")
        second.sendall(b'{"type": "start"}\n')
        thread.join(timeout=5)
        assert not thread.is_alive(), "lobby did not start after a valid start message"
        assert [client.name for client in result] == ["first", "second", "third"]

        for sock in (first, second, third):
            sock.close()
        for client in result:
            client.sock.close()
