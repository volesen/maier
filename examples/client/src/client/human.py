"""Interactive human player: prints the table each turn and reads an action
from stdin. Run the server with a generous turn deadline, or it will autoplay
for you after the default five seconds."""

from client.types import (
    Action,
    Challenge,
    Challenged,
    Claim,
    Claimed,
    Eliminated,
    EventBase,
    Reroll,
    Rerolled,
    Reveal,
    Roll,
    Rolled,
    State,
)


def on_event(event: EventBase) -> None:
    match event:
        case Rolled(player=player):
            print(f"* {player} rolled")
        case Rerolled(player=player):
            print(f"* {player} passed a blind reroll")
        case Claimed(player=player, rank=rank):
            print(f"* {player} claimed {rank}")
        case Challenged(challenger=challenger, claimant=claimant):
            print(f"* {challenger} challenged {claimant}")
        case Reveal(claimant=claimant, actual=actual, claimed=claimed, loser=loser) as reveal:
            print(
                f"* reveal: {claimant} claimed {claimed}, actual was {actual} — "
                f"{loser} loses {reveal.lives_lost} "
                f"{'life' if reveal.lives_lost == 1 else 'lives'}"
            )
        case Eliminated(player=player):
            print(f"* {player} is eliminated")
        case _:
            print(f"* {event}")


def _describe(legal: list[Action]) -> str:
    parts = []
    if any(isinstance(action, Roll) for action in legal):
        parts.append("roll (r)")
    if any(isinstance(action, Challenge) for action in legal):
        parts.append("challenge (c)")
    ranks = [action.rank for action in legal if isinstance(action, Claim)]
    if ranks:
        parts.append(f"claim {min(ranks)}-{max(ranks)} (enter a number)")
    if any(isinstance(action, Reroll) for action in legal):
        parts.append("reroll (rr)")
    return ", ".join(parts)


def _parse(text: str) -> Action | None:
    text = text.strip().lower()
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


def decide(state: State, legal: list[Action]) -> Action:
    lives = " ".join(f"{player}={state.lives[player]}" for player in state.turn_order)
    print()
    print(f"=== your turn ({state.you}, round {state.round}) === lives: {lives}")
    if state.current_claim is not None:
        blind = " (standing on a blind reroll)" if state.rerolled else ""
        print(f"claim on table: {state.current_claim} by {state.claimant}{blind}")
    if state.my_roll is not None:
        print(f"your roll: {state.my_roll}")
    print(f"legal: {_describe(legal)}")
    while True:
        try:
            text = input("> ")
        except EOFError:
            raise SystemExit("stdin closed, quitting") from None
        action = _parse(text)
        if action is not None and action in legal:
            return action
        print(f"invalid — legal: {_describe(legal)}")
