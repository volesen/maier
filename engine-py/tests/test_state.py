"""Ports of the Rust unit tests plus a randomized playthrough test mirroring
the Rust fuzz target (`engine/fuzz/fuzz_targets/play_game.rs`)."""

import random

import pytest

from engine_py.state import (
    ClaimAction,
    Dice,
    NewGame,
    NextStage,
    NextTurn,
    PlayerIndex,
    RerollAction,
    Roll,
    Stage1Action,
    Stage1State,
    Stage2State,
    Win,
    _CurrentRoll,
)

# --- Dice / Roll ---------------------------------------------------------


def test_dice_is_deterministic_for_a_seed() -> None:
    a = Dice(42)
    b = Dice(42)
    for _ in range(100):
        assert a.roll() == b.roll()


def test_different_seeds_generally_differ() -> None:
    a = Dice(1)
    b = Dice(2)
    # Extremely unlikely all 20 rolls coincide if the seed matters.
    assert any(a.roll() != b.roll() for _ in range(20))


def test_roll_saturates_at_max() -> None:
    assert Roll.from_value(255) == Roll(value=Roll.MAX)
    assert Roll.from_value(3) == Roll(value=3)


def test_roll_ordering() -> None:
    assert Roll(value=3) < Roll(value=4)
    assert Roll(value=4) <= Roll(value=4)
    assert Roll(value=5) > Roll(value=4)


# --- next_player ---------------------------------------------------------


def state_with_lives(player_lives: list[int], cur_player: int) -> Stage2State:
    """Build a minimal state with the given lives and current player.

    Uses a fixed dice seed; the roll value is irrelevant for these tests.
    """
    dice = Dice(0)
    cur_roll = _CurrentRoll.create(dice, PlayerIndex(index=cur_player))
    return Stage2State(
        dice=dice,
        cur_roll=cur_roll,
        newest_claim=None,
        reroll=False,
        cur_player=PlayerIndex(index=cur_player),
        player_lives=player_lives,
    )


def test_next_player_wraps_around() -> None:
    state = state_with_lives([1, 1, 1], 2)
    assert state._next_player() == PlayerIndex(index=0)


def test_next_player_skips_dead_players() -> None:
    # Player 1 is out; from player 0 the next alive is player 2.
    state = state_with_lives([1, 0, 1], 0)
    assert state._next_player() == PlayerIndex(index=2)


def test_next_player_returns_none_when_only_current_has_lives() -> None:
    state = state_with_lives([0, 3, 0], 1)
    assert state._next_player() is None


# --- Full games (port of the fuzz target) --------------------------------


def check_invariants(lives: list[int], cur_player: int, prev_total: int) -> None:
    """Assert the invariants that must hold on any live (not-yet-won) state."""
    total = sum(lives)

    # Lives never increase, and a single resolved round removes at most one.
    assert total <= prev_total, "total lives increased"
    assert prev_total - total <= 1, "more than one life lost in a single transition"

    # The game is not over, so at least two players must still be alive.
    alive = sum(1 for life in lives if life > 0)
    assert alive >= 2, "live state has fewer than two players alive"

    # Play must always rest on a player who still has lives.
    assert cur_player < len(lives), "cur_player out of range"
    assert lives[cur_player] > 0, "it is a dead player's turn"


def check_win(lives_before: list[int], winner: int) -> None:
    """A reported winner must have been alive going into the final round."""
    assert winner < len(lives_before), "winner index out of range"
    assert lives_before[winner] > 0, "winner had no lives before the final round"


@pytest.mark.parametrize("game_seed", range(200))
def test_random_playthrough_upholds_invariants(game_seed: int) -> None:
    """Drive whole games with random valid actions, asserting the engine's
    invariants after every transition, and that every game terminates."""
    rng = random.Random(game_seed)
    num_players = rng.randint(2, 6)
    lives = rng.randint(1, 5)
    dice_seed = rng.getrandbits(64)

    game: Stage1State | Stage2State = Stage2State.new(num_players, lives, dice_seed)

    # Hard cap: every resolved round removes a life, so a game can never
    # legitimately run this long; hitting the cap means no progress was made.
    max_steps = num_players * lives * 1000 + 1000

    for _ in range(max_steps):
        lives_before = game.player_lives()
        prev_total = sum(lives_before)

        if isinstance(game, Stage1State):
            stage1_action = rng.choice([Stage1Action.ROLL, Stage1Action.CHALLENGE])
            result1 = game.apply_stage1_action(stage1_action)
            if isinstance(result1, Win):
                check_win(lives_before, result1.winner.index)
                return
            assert isinstance(result1, NextStage)
            game = result1.state
        else:
            stage2_action: ClaimAction | RerollAction
            if rng.random() < 0.5:
                stage2_action = ClaimAction(roll=Roll.from_value(rng.randint(0, Roll.MAX)))
            else:
                stage2_action = RerollAction()
            result2 = game.apply_stage2_action(stage2_action)
            if isinstance(result2, Win):
                check_win(lives_before, result2.winner.index)
                return
            assert isinstance(result2, NextTurn | NewGame)
            game = result2.state

        check_invariants(game.player_lives(), game.cur_player().index, prev_total)

    pytest.fail(f"game did not terminate within {max_steps} steps")
