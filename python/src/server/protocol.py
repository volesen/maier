"""Pydantic models for the Meyer wire protocol (JSON lines over TCP).

Mirrors the Rust server's `server/src/protocol.rs` and the example client's
`examples/client/src/client/types.py`. Ranks on the wire run from 1 (the
lowest roll) to 21 (the highest); the engine's `Roll` values 0..=20 map to
ranks by adding one.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

MAX_RANK = 21
"""Highest rank on the wire; the engine's `Roll.MAX` plus one."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


# --- Actions --------------------------------------------------------------


class Roll(_Frozen):
    action: Literal["roll"] = "roll"


class Challenge(_Frozen):
    action: Literal["challenge"] = "challenge"


class Claim(_Frozen):
    action: Literal["claim"] = "claim"
    rank: int = Field(ge=1, le=MAX_RANK)


class Reroll(_Frozen):
    action: Literal["reroll"] = "reroll"


Action = Annotated[Roll | Challenge | Claim | Reroll, Field(discriminator="action")]


# --- Client -> server ------------------------------------------------------


class Join(_Frozen):
    type: Literal["join"] = "join"
    name: str
    protocol: int | None = None


class Act(_Frozen):
    type: Literal["act"] = "act"
    request_id: str
    action: Action


ClientMessage = Annotated[Join | Act, Field(discriminator="type")]

client_message_adapter = TypeAdapter[Join | Act](ClientMessage)


# --- Server -> client -------------------------------------------------------


class State(_Frozen):
    """Everything a player is allowed to observe, sent with every turn request."""

    you: str
    round: int
    my_roll: int | None
    """Rank of your hidden roll, once you have rolled this turn."""
    current_claim: int | None
    claimant: str | None
    lives: dict[str, int]
    turn_order: list[str]
    rerolled: bool
    """Whether the claim on the table now rests on a blind reroll."""


class Welcome(_Frozen):
    type: Literal["welcome"] = "welcome"
    player_id: str


class PlayerInfo(_Frozen):
    id: str
    name: str


class GameStart(_Frozen):
    type: Literal["game_start"] = "game_start"
    players: list[PlayerInfo]
    lives: int


class RoundStart(_Frozen):
    type: Literal["round_start"] = "round_start"
    round: int
    starting_player: str


class Turn(_Frozen):
    type: Literal["turn"] = "turn"
    request_id: str
    state: State
    legal_actions: list[Action]


class EventBase(_Frozen):
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


class GameEnd(_Frozen):
    type: Literal["game_end"] = "game_end"
    winner: str


ServerMessage = Annotated[
    Welcome | GameStart | RoundStart | Turn | Event | GameEnd,
    Field(discriminator="type"),
]

server_message_adapter = TypeAdapter[
    Welcome
    | GameStart
    | RoundStart
    | Turn
    | Rolled
    | Rerolled
    | Claimed
    | Challenged
    | Reveal
    | Eliminated
    | GameEnd
](ServerMessage)
