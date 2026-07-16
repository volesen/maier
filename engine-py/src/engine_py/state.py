"""Game state machine, ported from the Rust `engine` crate (`engine/src/state.rs`).

The Rust version uses the typestate pattern (`State<Stage1>` / `State<Stage2>`)
with move semantics. Here each stage is its own class and the `apply_*` methods
mutate the underlying state and hand it back wrapped in a result object; the
state instance an action was applied to must not be used afterwards.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum, auto
from functools import total_ordering
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


@total_ordering
class Roll(BaseModel):
    """A single dice roll in the range 0..=20."""

    model_config = ConfigDict(frozen=True)

    MAX: ClassVar[int] = 20

    value: int = Field(ge=0, le=20)

    @classmethod
    def from_value(cls, value: int) -> Roll:
        """Construct a `Roll` from a raw value, saturating at `Roll.MAX` so a
        `Roll` can never represent a value the dice could not produce. Intended
        for tests, where rolls must be built without a `Dice`."""
        return cls(value=min(value, cls.MAX))

    def __lt__(self, other: Roll) -> bool:
        return self.value < other.value


class Dice:
    """Seeded random source producing uniform rolls in 0..=20.

    Deterministic for a given seed within this implementation, but the
    sequence does not match the Rust engine (which uses ChaCha20).
    """

    def __init__(self, seed: int) -> None:
        self._rng = random.Random(seed)

    def roll(self) -> Roll:
        return Roll(value=self._rng.randint(0, Roll.MAX))


class PlayerIndex(BaseModel):
    model_config = ConfigDict(frozen=True)

    index: int = Field(ge=0)


class Stage1Action(Enum):
    ROLL = auto()
    CHALLENGE = auto()


class ClaimAction(BaseModel):
    """Stage 2 action: claim a roll value."""

    model_config = ConfigDict(frozen=True)

    roll: Roll


class RerollAction(BaseModel):
    """Stage 2 action: pass the (hidden) reroll on to the next player."""

    model_config = ConfigDict(frozen=True)


Stage2Action = ClaimAction | RerollAction


class _Claim(BaseModel):
    model_config = ConfigDict(frozen=True)

    claim: Roll
    claimer: PlayerIndex


class _CurrentRoll(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    roll: Roll
    roller: PlayerIndex

    @classmethod
    def create(cls, dice: Dice, roller: PlayerIndex) -> _CurrentRoll:
        return cls(roll=dice.roll(), roller=roller)


class _State:
    """State shared by both stages. Not constructed directly by users; games
    start via `Stage2State.new`."""

    def __init__(
        self,
        dice: Dice,
        cur_roll: _CurrentRoll,
        newest_claim: _Claim | None,
        reroll: bool,
        cur_player: PlayerIndex,
        player_lives: list[int],
    ) -> None:
        self._dice = dice
        self._cur_roll = cur_roll
        self._newest_claim = newest_claim
        self._reroll = reroll
        self._cur_player = cur_player
        self._player_lives = player_lives

    def player_lives(self) -> list[int]:
        """Lives remaining for each player, indexed by player."""
        return list(self._player_lives)

    def cur_player(self) -> PlayerIndex:
        """The player whose turn it currently is."""
        return self._cur_player

    def roll(self) -> Roll:
        return self._cur_roll.roll

    def newest_claim(self) -> Roll | None:
        """The claim currently on the table, if any."""
        return self._newest_claim.claim if self._newest_claim is not None else None

    def _next_player(self) -> PlayerIndex | None:
        # Find first player with lives left after current player
        num_players = len(self._player_lives)
        next_index = (self._cur_player.index + 1) % num_players
        while self._player_lives[next_index] == 0:
            next_index = (next_index + 1) % num_players
            if next_index == self._cur_player.index:
                # All other players are out of lives
                return None
        return PlayerIndex(index=next_index)

    def _switch_to_next_player(self) -> None:
        next_player = self._next_player()
        if next_player is None:
            raise RuntimeError("No other players have lives. Should have been caught elsewhere.")
        self._cur_player = next_player

    def _new_roll(self) -> _CurrentRoll:
        return _CurrentRoll.create(self._dice, self._cur_player)

    def _end_game(self, loser: PlayerIndex) -> PlayerIndex | None:
        """Deduct a life from `loser` and reset for a new round. Returns the
        winner if only one player has lives left."""
        if self._player_lives[loser.index] == 0:
            raise RuntimeError("Loser has no lives left to lose.")
        self._player_lives[loser.index] -= 1
        # Check if there is only one player left with lives and return that player if so
        alive_players = [
            PlayerIndex(index=index) for index, lives in enumerate(self._player_lives) if lives > 0
        ]
        if len(alive_players) == 1:
            return alive_players[0]
        if loser == self._cur_player:
            self._switch_to_next_player()
        self._cur_roll = self._new_roll()
        self._newest_claim = None
        self._reroll = False
        return None


class Stage1State(_State):
    """Stage 1: the current player reacts to the previous player's claim,
    either rolling or challenging."""

    def apply_stage1_action(self, action: Stage1Action) -> Stage1Result:
        newest_claim = self._newest_claim
        if newest_claim is None:
            raise RuntimeError("If there is no claim, stage 1 should be skipped.")
        if self._reroll:
            if action is Stage1Action.ROLL:
                self._cur_roll = self._new_roll()
                self._reroll = False
            else:
                if self._cur_roll.roll > newest_claim.claim:
                    # Challenger loses a life.
                    loser = self._cur_player
                else:
                    # Previous player loses a life.
                    loser = self._cur_roll.roller
                winner = self._end_game(loser)
                if winner is not None:
                    return Win(winner=winner)
        else:
            if action is Stage1Action.ROLL:
                self._cur_roll = self._new_roll()
            else:
                if self._cur_roll.roll == newest_claim.claim:
                    # Challenger loses a life
                    loser = self._cur_player
                else:
                    # Claimer loses a life
                    loser = newest_claim.claimer
                winner = self._end_game(loser)
                if winner is not None:
                    return Win(winner=winner)
        return NextStage(state=self._into_stage2())

    def _into_stage2(self) -> Stage2State:
        return Stage2State(
            dice=self._dice,
            cur_roll=self._cur_roll,
            newest_claim=self._newest_claim,
            reroll=self._reroll,
            cur_player=self._cur_player,
            player_lives=self._player_lives,
        )


class Stage2State(_State):
    """Stage 2: the current player either claims a value or passes a reroll."""

    @classmethod
    def new(cls, num_players: int, player_lives: int, dice_seed: int) -> Stage2State:
        if num_players < 2:
            raise ValueError("A game needs at least two players.")
        if player_lives < 1:
            raise ValueError("Players need at least one life.")
        dice = Dice(dice_seed)
        cur_roll = _CurrentRoll.create(dice, PlayerIndex(index=0))
        return cls(
            dice=dice,
            cur_roll=cur_roll,
            newest_claim=None,
            reroll=False,
            cur_player=PlayerIndex(index=0),
            player_lives=[player_lives] * num_players,
        )

    def apply_stage2_action(self, action: Stage2Action) -> Stage2Result:
        if self._reroll:
            raise RuntimeError(
                "Rerolls must be started in the previous player's stage 2, "
                "so cannot still be active in stage 2."
            )
        if self._newest_claim is not None:
            cur_claim = self._newest_claim.claim
            if isinstance(action, ClaimAction):
                if action.roll <= cur_claim:
                    # When it's current player that loses, this always moves to next player.
                    winner = self._end_game(self._cur_player)
                    if winner is not None:
                        return Win(winner=winner)
                    return NewGame(state=self)
                self._newest_claim = _Claim(claim=action.roll, claimer=self._cur_player)
                self._switch_to_next_player()
                return NextTurn(state=self._into_stage1())
            else:
                self._reroll = True
                self._cur_roll = self._new_roll()
                self._switch_to_next_player()
                return NextTurn(state=self._into_stage1())
        else:
            if isinstance(action, ClaimAction):
                self._newest_claim = _Claim(claim=action.roll, claimer=self._cur_player)
                self._switch_to_next_player()
                return NextTurn(state=self._into_stage1())
            else:
                winner = self._end_game(self._cur_player)
                if winner is not None:
                    return Win(winner=winner)
                return NewGame(state=self)

    def _into_stage1(self) -> Stage1State:
        return Stage1State(
            dice=self._dice,
            cur_roll=self._cur_roll,
            newest_claim=self._newest_claim,
            reroll=self._reroll,
            cur_player=self._cur_player,
            player_lives=self._player_lives,
        )


@dataclass(frozen=True)
class NextStage:
    """Stage 1 resolved without ending the game; play continues in stage 2."""

    state: Stage2State


@dataclass(frozen=True)
class NextTurn:
    """Stage 2 passed play to the next player's stage 1."""

    state: Stage1State


@dataclass(frozen=True)
class NewGame:
    """A round ended (a life was lost) and a fresh round starts in stage 2."""

    state: Stage2State


@dataclass(frozen=True)
class Win:
    """The game is over; only one player has lives left."""

    winner: PlayerIndex


Stage1Result = NextStage | Win
Stage2Result = NextTurn | NewGame | Win
