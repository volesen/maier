"""Baseline bots, from exploitable extremes to odds-based play."""

import random

from client.types import Action, Challenge, Claim, Decide, Reroll, Roll, State

COUNTS = {rank: 1 if 14 <= rank <= 19 else 2 for rank in range(1, 22)}
"""Ways to roll each rank out of 36 ordered outcomes; pairs are single outcomes."""

P_AT_LEAST = {
    rank: sum(COUNTS[r] for r in range(rank, 22)) / 36 for rank in range(1, 22)
}
"""Probability that a fresh roll ranks at least `rank`."""


def _can(legal: list[Action], kind: type) -> bool:
    return any(isinstance(action, kind) for action in legal)


def _min_claim(legal: list[Action]) -> int:
    return min(action.rank for action in legal if isinstance(action, Claim))


def _truthful_claim(state: State, legal: list[Action]) -> Claim:
    """Claim the truth when legal, otherwise the smallest lie."""
    assert state.my_roll is not None
    return Claim(rank=max(state.my_roll, _min_claim(legal)))


def random_bot(state: State, legal: list[Action]) -> Action:
    return random.choice(legal)


def honest(state: State, legal: list[Action]) -> Action:
    """Never challenges unless forced, never rerolls, lies as little as possible."""
    if state.my_roll is None:
        return Roll() if _can(legal, Roll) else Challenge()
    return _truthful_claim(state, legal)


def minimal(state: State, legal: list[Action]) -> Action:
    """Always claims the smallest legal rank, regardless of its roll."""
    if state.my_roll is None:
        return Roll() if _can(legal, Roll) else Challenge()
    return Claim(rank=_min_claim(legal))


def paranoid(state: State, legal: list[Action]) -> Action:
    """Challenges whenever challenging is legal."""
    if state.my_roll is None:
        return Challenge() if _can(legal, Challenge) else Roll()
    return _truthful_claim(state, legal)


def cutoff(threshold: float = 0.3) -> Decide:
    """Challenges iff a fresh roll would make the claim with probability < threshold.

    P(roll >= claim) decreases with the claim, so this is "challenge any claim at
    or above a fixed rank"; threshold 0 never challenges, threshold 1 always does.
    """

    def decide(state: State, legal: list[Action]) -> Action:
        if state.my_roll is None:
            if not _can(legal, Roll):
                return Challenge()
            if (
                _can(legal, Challenge)
                and state.current_claim is not None
                and P_AT_LEAST[state.current_claim] < threshold
            ):
                return Challenge()
            return Roll()
        return _truthful_claim(state, legal)

    return decide


def statistician(threshold: float = 0.3) -> Decide:
    """`cutoff`, plus rerolling whenever it would otherwise have to lie."""
    base = cutoff(threshold)

    def decide(state: State, legal: list[Action]) -> Action:
        if (
            state.my_roll is not None
            and _can(legal, Reroll)
            and state.my_roll < _min_claim(legal)
        ):
            return Reroll()
        return base(state, legal)

    return decide
