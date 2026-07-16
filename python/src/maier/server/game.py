"""TCP game server, structured after the Rust server (`server/src/main.rs`) but
using the `engine` package as the rules engine.

The engine plays a two-stage variant: in stage 1 the current player reacts to
the claim on the table (roll their own dice, or challenge); in stage 2 they
know their hidden roll and either claim a rank or pass a blind reroll to the
next player. The server only ever offers actions that the engine accepts and
that do not automatically forfeit a life, so every reply a client can pick is
meaningful.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import random
import select
import socket
import sys
import threading
import time

from pydantic import BaseModel, ValidationError

from maier.engine import state as eng
from maier.server import protocol as proto

LIVES = 6
DEFAULT_TURN_DEADLINE_MS = 5000
JOIN_DEADLINE_S = 10.0


def _to_rank(roll: eng.Roll) -> int:
    return roll.value + 1


def _rank_to_roll(rank: int) -> eng.Roll:
    return eng.Roll(value=rank - 1)


class LineReader:
    """Buffered newline-delimited reader with an absolute deadline per line."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._buf = b""

    def read_line(self, deadline: float) -> str | None:
        """Read one line, or return None on timeout, disconnect, or error."""
        while b"\n" not in self._buf:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            self._sock.settimeout(remaining)
            try:
                chunk = self._sock.recv(4096)
            except OSError:
                return None
            if not chunk:
                return None  # disconnected
            self._buf += chunk
        return self.try_buffered_line()

    def fill(self) -> bool:
        """Read once from the socket into the buffer; False on disconnect or error.

        Only call when the socket is known to be readable (e.g. after select),
        otherwise this may block for up to a second.
        """
        self._sock.settimeout(1.0)
        try:
            chunk = self._sock.recv(4096)
        except OSError:
            return False
        if not chunk:
            return False
        self._buf += chunk
        return True

    def try_buffered_line(self) -> str | None:
        """Pop a complete line from the buffer without touching the socket."""
        if b"\n" not in self._buf:
            return None
        line, _, self._buf = self._buf.partition(b"\n")
        return line.decode("utf-8", errors="replace")


class Client:
    def __init__(self, player_id: str, name: str, sock: socket.socket) -> None:
        self.id = player_id
        self.name = name
        self.sock = sock
        self.reader = LineReader(sock)

    def send(self, msg: BaseModel) -> None:
        line = json.dumps(msg.model_dump(mode="json")) + "\n"
        # A dead connection just means this player times out on their turns.
        with contextlib.suppress(OSError):
            self.sock.sendall(line.encode("utf-8"))


class Game:
    def __init__(self, clients: list[Client], turn_deadline_s: float, dice_seed: int) -> None:
        self._clients = clients
        self._turn_deadline_s = turn_deadline_s
        self._round = 0
        self._next_request_id = 0
        self._rng = random.Random()
        self._state: eng.Stage1State | eng.Stage2State = eng.Stage2State.new(
            len(clients), LIVES, dice_seed
        )
        # Who made the claim on the table, and who rolled the dice it will be
        # judged against; the engine keeps both hidden, so track them here.
        self._claimant: int | None = None
        self._roller: int = self._state.cur_player().index
        self._reroll_pending = False

    def run(self) -> None:
        self._broadcast(
            proto.GameStart(
                players=[proto.PlayerInfo(id=c.id, name=c.name) for c in self._clients],
                lives=LIVES,
            )
        )
        self._start_round()
        while True:
            if isinstance(self._state, eng.Stage2State):
                winner = self._play_stage2(self._state)
            else:
                winner = self._play_stage1(self._state)
            if winner is not None:
                print(
                    f"game over after {self._round} rounds, winner: {self._clients[winner].name}",
                    file=sys.stderr,
                )
                self._broadcast(proto.GameEnd(winner=self._id(winner)))
                return

    def _start_round(self) -> None:
        self._round += 1
        self._broadcast(
            proto.RoundStart(
                round=self._round,
                starting_player=self._id(self._state.cur_player().index),
            )
        )

    def _play_stage2(self, state: eng.Stage2State) -> int | None:
        """The current player knows their roll: claim a rank or pass a reroll."""
        cur = state.cur_player().index
        cur_claim = state.newest_claim()
        min_rank = 1 if cur_claim is None else _to_rank(cur_claim) + 1
        legal: list[proto.Roll | proto.Challenge | proto.Claim | proto.Reroll] = [
            proto.Claim(rank=rank) for rank in range(min_rank, proto.MAX_RANK + 1)
        ]
        if cur_claim is not None:
            # Rerolling with no claim on the table forfeits a life, so it is
            # only offered once there is a claim.
            legal.append(proto.Reroll())

        action = self._request(cur, my_roll=_to_rank(state.roll()), legal=legal)
        if isinstance(action, proto.Claim):
            result = state.apply_stage2_action(eng.ClaimAction(roll=_rank_to_roll(action.rank)))
            self._claimant = cur
            self._broadcast(proto.Claimed(player=self._id(cur), rank=action.rank))
        elif isinstance(action, proto.Reroll):
            result = state.apply_stage2_action(eng.RerollAction())
            self._roller = cur
            self._reroll_pending = True
            self._broadcast(proto.Rerolled(player=self._id(cur)))
        else:
            raise RuntimeError("not in legal actions")

        # Every offered action raises the claim or passes a reroll, so the
        # round cannot end here.
        if not isinstance(result, eng.NextTurn):
            raise RuntimeError("legal stage 2 actions never end a round")
        self._state = result.state
        return None

    def _play_stage1(self, state: eng.Stage1State) -> int | None:
        """The current player reacts to the claim: roll their own dice or challenge."""
        cur = state.cur_player().index
        claim = state.newest_claim()
        if claim is None or self._claimant is None:
            raise RuntimeError("stage 1 is only reached with a claim on the table")
        # Rolling after a maximum claim would leave nothing to claim, so only
        # challenging is offered (as in the Rust server).
        legal: list[proto.Roll | proto.Challenge | proto.Claim | proto.Reroll] = (
            [proto.Challenge()]
            if _to_rank(claim) == proto.MAX_RANK
            else [proto.Roll(), proto.Challenge()]
        )

        action = self._request(cur, my_roll=None, legal=legal)
        if isinstance(action, proto.Roll):
            result = state.apply_stage1_action(eng.Stage1Action.ROLL)
            self._roller = cur
            self._reroll_pending = False
            self._broadcast(proto.Rolled(player=self._id(cur)))
            if not isinstance(result, eng.NextStage):
                raise RuntimeError("rolling never ends a round")
            self._state = result.state
            return None
        if not isinstance(action, proto.Challenge):
            raise RuntimeError("not in legal actions")

        # Resolve the challenge by the engine's rules; the engine hides the
        # outcome details, so recompute the loser for the reveal broadcast.
        actual = state.roll()
        claimed_rank = _to_rank(claim)
        if self._reroll_pending:
            # A blind reroll must beat the claim.
            loser = cur if actual > claim else self._roller
        else:
            # A claim is honest only if it matches the roll exactly.
            loser = cur if actual == claim else self._claimant
        self._broadcast(
            proto.Challenged(challenger=self._id(cur), claimant=self._id(self._claimant))
        )
        result = state.apply_stage1_action(eng.Stage1Action.CHALLENGE)
        self._broadcast(
            proto.Reveal(
                claimant=self._id(self._claimant),
                actual=_to_rank(actual),
                claimed=claimed_rank,
                loser=self._id(loser),
                lives_lost=1,
            )
        )

        if isinstance(result, eng.Win):
            # The loser's last life is gone and only the winner remains.
            self._broadcast(proto.Eliminated(player=self._id(loser)))
            return result.winner.index
        if not isinstance(result, eng.NextStage):
            raise RuntimeError("unreachable: challenge yields NextStage or Win")
        if result.state.player_lives()[loser] == 0:
            self._broadcast(proto.Eliminated(player=self._id(loser)))
        self._state = result.state
        self._claimant = None
        self._roller = result.state.cur_player().index
        self._reroll_pending = False
        self._start_round()
        return None

    def _request(
        self,
        p: int,
        my_roll: int | None,
        legal: list[proto.Roll | proto.Challenge | proto.Claim | proto.Reroll],
    ) -> proto.Roll | proto.Challenge | proto.Claim | proto.Reroll:
        """Ask player `p` to pick one of `legal`; falls back to a random legal
        action on timeout, disconnect, or invalid reply."""
        self._next_request_id += 1
        request_id = str(self._next_request_id)
        claim = self._state.newest_claim()
        state = proto.State(
            you=self._id(p),
            round=self._round,
            my_roll=my_roll,
            current_claim=_to_rank(claim) if claim is not None else None,
            claimant=self._id(self._claimant) if self._claimant is not None else None,
            lives={
                client.id: lives
                for client, lives in zip(self._clients, self._state.player_lives(), strict=True)
            },
            turn_order=[client.id for client in self._clients],
            rerolled=self._reroll_pending,
        )
        client = self._clients[p]
        client.send(proto.Turn(request_id=request_id, state=state, legal_actions=legal))

        deadline = time.monotonic() + self._turn_deadline_s
        while True:
            line = client.reader.read_line(deadline)
            if line is None:
                break
            try:
                msg = proto.client_message_adapter.validate_json(line)
            except ValidationError:
                continue
            if isinstance(msg, proto.Act) and msg.request_id == request_id and msg.action in legal:
                return msg.action
            # Stale, malformed, or illegal reply: keep waiting.
        action = self._rng.choice(legal)
        print(f"{client.id}: no valid reply, autoplaying {action!r}", file=sys.stderr)
        return action

    def _broadcast(self, msg: BaseModel) -> None:
        for client in self._clients:
            client.send(msg)

    def _id(self, p: int) -> str:
        return self._clients[p].id


def accept_join(sock: socket.socket) -> tuple[proto.Join, LineReader]:
    sock.settimeout(JOIN_DEADLINE_S)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    reader = LineReader(sock)
    line = reader.read_line(time.monotonic() + JOIN_DEADLINE_S)
    if line is None:
        raise ValueError("no join message before the deadline")
    msg = proto.client_message_adapter.validate_json(line)
    if not isinstance(msg, proto.Join):
        raise ValueError("expected join")
    return msg, reader


class Lobby:
    """Players waiting for a game; created the first time its name is joined."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.clients: list[Client] = []
        self.next_seat = 0


def serve(listener: socket.socket, turn_deadline_s: float, dice_seed: int | None) -> None:
    """Accept joins into named lobbies forever; a lobby's game starts in its
    own thread when one of its players sends `start`, freeing the name."""
    lobbies: dict[str, Lobby] = {}

    def wants_start(lobby: Lobby, client: Client) -> bool:
        """Process the client's buffered lines; True on a valid start request."""
        while (line := client.reader.try_buffered_line()) is not None:
            try:
                msg = proto.client_message_adapter.validate_json(line)
            except ValidationError:
                continue
            if not isinstance(msg, proto.Start):
                continue
            if len(lobby.clients) < 2:
                print(
                    f"{client.id} asked to start lobby {lobby.name!r}, "
                    "but a game needs at least two players",
                    file=sys.stderr,
                )
                continue
            print(
                f"{client.id} started lobby {lobby.name!r} with {len(lobby.clients)} players",
                file=sys.stderr,
            )
            return True
        return False

    def start_game(lobby: Lobby) -> None:
        del lobbies[lobby.name]
        seed = dice_seed if dice_seed is not None else random.getrandbits(64)
        game = Game(lobby.clients, turn_deadline_s, seed)
        threading.Thread(target=game.run, name=f"game-{lobby.name}", daemon=True).start()

    while True:
        socks = [listener, *(c.sock for lobby in lobbies.values() for c in lobby.clients)]
        try:
            readable, _, _ = select.select(socks, [], [])
        except (OSError, ValueError):
            if listener.fileno() == -1:
                return  # listener closed: shut down
            # Drop lobby clients whose sockets have been closed under us.
            for lobby in list(lobbies.values()):
                lobby.clients = [c for c in lobby.clients if c.sock.fileno() != -1]
                if not lobby.clients:
                    del lobbies[lobby.name]
            continue
        for ready in readable:
            if ready is listener:
                sock, addr = listener.accept()
                try:
                    join, reader = accept_join(sock)
                except (ValueError, ValidationError, OSError) as err:
                    print(f"rejected connection from {addr}: {err}", file=sys.stderr)
                    sock.close()
                    continue
                lobby = lobbies.setdefault(join.lobby, Lobby(join.lobby))
                client = Client(player_id=f"p{lobby.next_seat}", name=join.name, sock=sock)
                client.reader = reader
                lobby.next_seat += 1
                lobby.clients.append(client)
                client.send(proto.Welcome(player_id=client.id, lobby=lobby.name))
                print(
                    f"{client.name} joined lobby {lobby.name!r} as {client.id} from {addr}",
                    file=sys.stderr,
                )
            else:
                found = next(
                    (
                        (lobby, client)
                        for lobby in lobbies.values()
                        for client in lobby.clients
                        if client.sock is ready
                    ),
                    None,
                )
                if found is None:
                    # The lobby started earlier in this select round; its game
                    # thread owns the socket now.
                    continue
                lobby, client = found
                if not client.reader.fill():
                    print(
                        f"{client.name} ({client.id}) left lobby {lobby.name!r}",
                        file=sys.stderr,
                    )
                    lobby.clients.remove(client)
                    client.sock.close()
                    if not lobby.clients:
                        del lobbies[lobby.name]
                    continue
            if wants_start(lobby, client):
                start_game(lobby)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a Meyer game server")
    parser.add_argument("port", nargs="?", type=int, default=5000)
    parser.add_argument("deadline_ms", nargs="?", type=int, default=DEFAULT_TURN_DEADLINE_MS)
    parser.add_argument("--seed", type=int, default=None, help="dice seed (random by default)")
    args = parser.parse_args()

    with socket.create_server(("0.0.0.0", args.port)) as listener:
        print(
            f"listening on port {args.port}; clients join named lobbies and any "
            'joined player sends {"type": "start"} to begin their lobby\'s game',
            file=sys.stderr,
        )
        serve(listener, args.deadline_ms / 1000, args.seed)
