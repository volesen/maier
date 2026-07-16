"""Integration test: run the server's game loop against bot clients over
socket pairs, checking the wire protocol end to end."""

import json
import random
import socket
import threading
import time

import pytest
from pydantic import BaseModel

from maier.server import protocol as proto
from maier.server.game import Client, Game, LineReader, serve


class BotResult(BaseModel):
    events: list[str]
    winner: str | None


def _run_bot(
    sock: socket.socket, rng_seed: int, result: BotResult, reader: LineReader | None = None
) -> None:
    """Picks a random legal action every turn until the game ends."""
    rng = random.Random(rng_seed)
    if reader is None:
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


def test_serve_hosts_multiple_lobbies() -> None:
    """Two named lobbies on one server, started independently, both games
    running concurrently to completion."""
    with socket.create_server(("127.0.0.1", 0)) as listener:
        port = listener.getsockname()[1]
        threading.Thread(
            target=serve,
            args=(listener, 5.0, None),
            daemon=True,
        ).start()

        def join(name: str, lobby: str) -> tuple[socket.socket, LineReader]:
            sock = socket.create_connection(("127.0.0.1", port), timeout=5)
            sock.sendall(
                (json.dumps({"type": "join", "name": name, "lobby": lobby}) + "\n").encode()
            )
            reader = LineReader(sock)
            line = reader.read_line(time.monotonic() + 5)
            assert line is not None
            welcome = proto.server_message_adapter.validate_python(json.loads(line))
            assert isinstance(welcome, proto.Welcome)
            assert welcome.lobby == lobby
            return sock, reader

        lobby_names = ["alpha", "beta"]
        connections = {name: [join(f"{name}-{i}", name) for i in range(2)] for name in lobby_names}

        # A start in a one-player lobby must be ignored.
        lone_sock, lone_reader = join("loner", "gamma")
        lone_sock.sendall(b'{"type": "start"}\n')
        time.sleep(0.2)
        assert lone_reader.try_buffered_line() is None, "one-player lobby must not start"

        results: dict[str, list[BotResult]] = {name: [] for name in lobby_names}
        threads = []
        for name in lobby_names:
            connections[name][0][0].sendall(b'{"type": "start"}\n')
            for i, (sock, reader) in enumerate(connections[name]):
                result = BotResult(events=[], winner=None)
                results[name].append(result)
                thread = threading.Thread(
                    target=_run_bot, args=(sock, i, result, reader), daemon=True
                )
                threads.append(thread)
                thread.start()

        for thread in threads:
            thread.join(timeout=15)
            assert not thread.is_alive(), "bot did not finish"

        for name in lobby_names:
            winners = {result.winner for result in results[name]}
            assert len(winners) == 1, f"lobby {name}: bots disagree on the winner"
            assert winners.pop() in {"p0", "p1"}
            for result in results[name]:
                assert "game_start" in result.events
                assert result.events[-1] == "game_end"

        lone_sock.close()
        for conns in connections.values():
            for sock, _ in conns:
                sock.close()
