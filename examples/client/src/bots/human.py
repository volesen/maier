"""Interactive human player.

Renders every server message as readable text (names instead of player ids,
lives, odds hints) and reads your action from stdin each turn. Run the server
with a generous turn deadline, or it will autoplay for you after the default
five seconds.
"""

from maier.client.types import (
    Action,
    Challenge,
    Challenged,
    Claim,
    Claimed,
    Eliminated,
    GameEnd,
    GameStart,
    Rerolled,
    Reroll,
    Reveal,
    Roll,
    Rolled,
    RoundStart,
    ServerMessage,
    State,
    Welcome,
)

_HELP = """\
actions:
  roll (r)       roll your own dice; you then claim a rank or pass a reroll
  challenge (c)  call the bluff — the claim only survives if it is exactly true;
                 a blind reroll survives only by beating the claim
  claim N        claim rank N (type the number, e.g. `15`); claiming anything
                 but your actual roll is a bluff and loses if challenged
  reroll (rr)    pass a hidden reroll of the dice to the next player
  help (?)       show this help"""


class HumanPlayer:
    """Stateful renderer + stdin prompt; pass `decide` and `on_message` to `run()`."""

    def __init__(self) -> None:
        self.you: str | None = None
        self.names: dict[str, str] = {}

    def _who(self, player_id: str | None) -> str:
        if player_id is None:
            return "?"
        if player_id == self.you:
            return "you"
        name = self.names.get(player_id)
        return f"{name} ({player_id})" if name else player_id

    def _verb(self, player_id: str, verb: str) -> str:
        """Third-person `verb` unless the player is you ("loses" vs "lose")."""
        return verb if player_id == self.you else verb + "s"

    def on_message(self, msg: ServerMessage) -> None:
        match msg:
            case Welcome():
                self.you = msg.player_id
                lobby = f" in lobby {msg.lobby!r}" if msg.lobby is not None else ""
                print(f"connected as {msg.player_id}{lobby}")
            case GameStart():
                self.names = {p.id: p.name for p in msg.players}
                players = ", ".join(self._who(p.id) for p in msg.players)
                print(f"\ngame on — {msg.lives} lives each: {players}")
            case RoundStart():
                starter = msg.starting_player
                print(f"\n─── round {msg.round}: {self._who(starter)} {self._verb(starter, 'start')} ───")
            case Rolled():
                print(f"  {self._who(msg.player)} {self._verb(msg.player, 'roll')} the dice")
            case Rerolled():
                print(
                    f"  {self._who(msg.player)} {self._verb(msg.player, 'pass')} "
                    "a hidden reroll to the next player"
                )
            case Claimed():
                print(f"  {self._who(msg.player)} {self._verb(msg.player, 'claim')} {msg.rank}")
            case Challenged():
                print(
                    f"  {self._who(msg.challenger)} "
                    f"{self._verb(msg.challenger, 'challenge')} {self._who(msg.claimant)}!"
                )
            case Reveal():
                lives = "life" if msg.lives_lost == 1 else "lives"
                print(
                    f"  the dice showed {msg.actual} against the claim of {msg.claimed} — "
                    f"{self._who(msg.loser)} {self._verb(msg.loser, 'lose')} {msg.lives_lost} {lives}"
                )
            case Eliminated():
                out = "are" if msg.player == self.you else "is"
                print(f"  {self._who(msg.player)} {out} out of the game")
            case GameEnd():
                if msg.winner == self.you:
                    print("\n🏆 you win!")
                else:
                    print(f"\n🏆 {self._who(msg.winner)} wins — better luck next time")
            case _:
                print(f"  {msg}")

    def _table(self, state: State) -> None:
        print()
        print(f"┌─ round {state.round} — your turn")
        lives = "  ".join(
            f"{self._who(pid)} {'♥' * n if n else 'out'}"
            for pid, n in ((pid, state.lives[pid]) for pid in state.turn_order)
        )
        print(f"│ lives: {lives}")
        claim = state.current_claim
        if claim is not None:
            reroll = ", now standing on a hidden reroll" if state.rerolled else ""
            print(f"│ claim: {claim} by {self._who(state.claimant)}{reroll}")
        if state.my_roll is not None:
            print(f"│ your roll: {state.my_roll} (hidden from the others)")

    def _options(self, state: State, legal: list[Action]) -> str:
        parts = []
        if any(isinstance(a, Roll) for a in legal):
            parts.append("roll (r)")
        if any(isinstance(a, Challenge) for a in legal):
            parts.append("challenge (c)")
        ranks = [a.rank for a in legal if isinstance(a, Claim)]
        if ranks:
            parts.append(f"claim {min(ranks)}–{max(ranks)} (a number)")
        if any(isinstance(a, Reroll) for a in legal):
            parts.append("reroll (rr)")
        parts.append("help (?)")
        return ", ".join(parts)

    def decide(self, state: State, legal: list[Action]) -> Action:
        self._table(state)
        ranks = [a.rank for a in legal if isinstance(a, Claim)]
        if ranks and state.my_roll is not None and state.my_roll < min(ranks):
            hint = "you must bluff" + (
                " or pass a reroll" if any(isinstance(a, Reroll) for a in legal) else ""
            )
            print(f"│ your roll can no longer be claimed truthfully — {hint}")
        print(f"└ {self._options(state, legal)}")
        while True:
            try:
                text = input("> ").strip().lower()
            except EOFError:
                raise SystemExit("stdin closed, quitting") from None
            if text in {"?", "h", "help"}:
                print(_HELP)
                continue
            action = _parse(text)
            if action is not None and action in legal:
                return action
            if text:
                print(f"'{text}' is not available — {self._options(state, legal)}")


def _parse(text: str) -> Action | None:
    if text in {"r", "roll"}:
        return Roll()
    if text in {"c", "challenge"}:
        return Challenge()
    if text in {"rr", "reroll"}:
        return Reroll()
    if text.startswith("claim"):
        text = text.removeprefix("claim").strip()
    if text.isdigit():
        return Claim(rank=int(text))
    return None
