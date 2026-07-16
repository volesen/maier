"""The client loop: connect, join a lobby, and answer turn requests."""

import json
import select
import socket
import sys
from collections.abc import Callable

from pydantic import TypeAdapter

from maier.client.types import (
    Decide,
    EventBase,
    GameEnd,
    GameStart,
    OnEvent,
    OnMessage,
    ServerMessage,
    Turn,
)

_server_message = TypeAdapter[ServerMessage](ServerMessage)


def _recv_line(sock: socket.socket, buf: bytearray) -> str | None:
    """Blocking read of one newline-terminated line; None once disconnected."""
    while b"\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            return None
        buf += chunk
    line, _, rest = bytes(buf).partition(b"\n")
    buf[:] = rest
    return line.decode()


def _buffered_line(buf: bytearray) -> str | None:
    """Pop a complete line from the buffer without touching the socket."""
    if b"\n" not in buf:
        return None
    line, _, rest = bytes(buf).partition(b"\n")
    buf[:] = rest
    return line.decode()


def _lobby(
    sock: socket.socket,
    buf: bytearray,
    send: Callable[[dict[str, object]], None],
    handle: Callable[[str], object],
) -> None:
    """Wait for the game to begin, letting the user start it from stdin."""
    print("waiting in lobby; type 'start' (or press enter) to begin with all joined players")
    inputs = [sock, sys.stdin]
    while True:
        while (line := _buffered_line(buf)) is not None:
            if isinstance(handle(line), GameStart):
                return
        readable, _, _ = select.select(inputs, [], [])
        if sys.stdin in readable:
            cmd = sys.stdin.readline()
            if not cmd:  # stdin closed; keep waiting on the server alone
                inputs.remove(sys.stdin)
            elif cmd.strip().lower() in {"", "start"}:
                send({"type": "start"})
            else:
                print("type 'start' (or press enter) to begin the game")
        if sock in readable:
            chunk = sock.recv(4096)
            if not chunk:
                raise ConnectionError("server closed the connection")
            buf += chunk


def run(
    decide: Decide,
    name: str,
    host: str = "127.0.0.1",
    port: int = 5000,
    on_event: OnEvent | None = None,
    on_message: OnMessage | None = None,
    start: bool = False,
    interactive_start: bool = False,
    lobby: str | None = None,
) -> None:
    """Join a game and play it with `decide`, returning when the game ends.

    - `on_message` receives every non-turn server message (nothing is printed);
      without it, `on_event` receives broadcast game events and everything else
      is printed as raw JSON lines.
    - `start` asks the server to begin the lobby's game immediately on joining;
      `interactive_start` instead lets the user trigger it from stdin.
    - `lobby` selects a named lobby, created on first use (server default
      lobby otherwise).
    """
    with socket.create_connection((host, port)) as sock:
        buf = bytearray()

        def send(obj: dict[str, object]) -> None:
            sock.sendall((json.dumps(obj) + "\n").encode())

        def handle(line: str) -> ServerMessage | None:
            """Process one server message; returns None once the game has ended."""
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
                    return msg
                case _ if on_message is not None:
                    on_message(msg)
                case EventBase() if on_event is not None:
                    on_event(msg)
                case _:
                    print(line)
            return None if isinstance(msg, GameEnd) else msg

        join: dict[str, object] = {"type": "join", "name": name, "protocol": 1}
        if lobby is not None:
            join["lobby"] = lobby
        send(join)
        if start:
            send({"type": "start"})
        if interactive_start:
            _lobby(sock, buf, send, handle)
        while (line := _recv_line(sock, buf)) is not None:
            if handle(line) is None:
                return
