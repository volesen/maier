"""Pydantic models for the Meyer wire protocol (JSON lines over TCP)."""

from collections.abc import Callable
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class Roll(BaseModel):
    action: Literal["roll"] = "roll"


class Challenge(BaseModel):
    action: Literal["challenge"] = "challenge"


class Claim(BaseModel):
    action: Literal["claim"] = "claim"
    rank: int


class Reroll(BaseModel):
    action: Literal["reroll"] = "reroll"


Action = Annotated[Roll | Challenge | Claim | Reroll, Field(discriminator="action")]


class State(BaseModel):
    """Everything you are allowed to observe, sent with every turn request."""

    you: str
    round: int
    my_roll: int | None
    """Rank of your hidden roll, 1 (3-2) to 21 (Meyer), once you have rolled."""
    current_claim: int | None
    claimant: str | None
    lives: dict[str, int]
    turn_order: list[str]
    rerolled: bool


class Welcome(BaseModel):
    type: Literal["welcome"] = "welcome"
    player_id: str


class PlayerInfo(BaseModel):
    id: str
    name: str


class GameStart(BaseModel):
    type: Literal["game_start"] = "game_start"
    players: list[PlayerInfo]
    lives: int


class RoundStart(BaseModel):
    type: Literal["round_start"] = "round_start"
    round: int
    starting_player: str


class Turn(BaseModel):
    type: Literal["turn"] = "turn"
    request_id: str
    state: State
    legal_actions: list[Action]


class EventBase(BaseModel):
    """Broadcast game event."""

    type: Literal["event"] = "event"


class Rolled(EventBase):
    event: Literal["rolled"] = "rolled"
    player: str


class Rerolled(EventBase):
    event: Literal["rerolled"] = "rerolled"
    player: str


class Claimed(EventBase):
    event: Literal["claimed"] = "claimed"
    player: str
    rank: int


class Challenged(EventBase):
    event: Literal["challenged"] = "challenged"
    challenger: str
    claimant: str


class Reveal(EventBase):
    event: Literal["reveal"] = "reveal"
    claimant: str
    actual: int
    claimed: int
    loser: str
    lives_lost: int


class Eliminated(EventBase):
    event: Literal["eliminated"] = "eliminated"
    player: str


Event = Annotated[
    Rolled | Rerolled | Claimed | Challenged | Reveal | Eliminated,
    Field(discriminator="event"),
]


class GameEnd(BaseModel):
    type: Literal["game_end"] = "game_end"
    winner: str


ServerMessage = Annotated[
    Welcome | GameStart | RoundStart | Turn | Event | GameEnd,
    Field(discriminator="type"),
]

Decide = Callable[[State, list[Action]], Action]
"""A bot: picks one of the legal actions given the observable state."""

OnEvent = Callable[[EventBase], None]
"""Optional listener for broadcast game events."""
