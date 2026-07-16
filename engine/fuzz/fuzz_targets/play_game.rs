#![no_main]

//! Fuzz target that plays whole games of the dice engine.
//!
//! The raw fuzzer bytes are decoded into a game configuration (player count,
//! starting lives, dice seed) followed by a stream of actions. We drive the
//! state machine to completion, feeding it only *valid* actions, and after
//! every transition assert the engine's invariants. Because every action fed
//! in is valid, ANY panic — an engine `assert!`/`expect`, an arithmetic
//! underflow, or one of our invariant asserts below — is a genuine bug and is
//! reported by libFuzzer as a crash.

use engine::state::{
    Roll, Stage1, Stage1Action, Stage1Result, Stage2, Stage2Action, Stage2Result, State,
};
use libfuzzer_sys::fuzz_target;

/// Pulls bytes off the front of the fuzzer input to make decisions. When the
/// input is exhausted it yields 0, so a short input simply drives a short game.
struct ByteStream<'a> {
    bytes: &'a [u8],
    pos: usize,
}

impl<'a> ByteStream<'a> {
    fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, pos: 0 }
    }

    fn next(&mut self) -> u8 {
        let b = self.bytes.get(self.pos).copied().unwrap_or(0);
        self.pos += 1;
        b
    }

    /// Whether every byte has been consumed. Used to stop driving the game
    /// once the fuzzer's script runs out.
    fn exhausted(&self) -> bool {
        self.pos >= self.bytes.len()
    }
}

/// Either stage of the game, so we can hold "the current game state" across
/// transitions between stages.
enum Game {
    Stage1(State<Stage1>),
    Stage2(State<Stage2>),
}

/// Assert the invariants that must hold on any live (not-yet-won) state.
fn check_invariants(lives: &[u32], cur_player: usize, prev_total: u32) {
    let total: u32 = lives.iter().sum();

    // Lives never increase, and a single resolved round removes at most one.
    assert!(total <= prev_total, "total lives increased");
    assert!(
        prev_total - total <= 1,
        "more than one life lost in a single transition",
    );

    // The game is not over, so at least two players must still be alive.
    let alive = lives.iter().filter(|&&l| l > 0).count();
    assert!(alive >= 2, "live state has fewer than two players alive");

    // Play must always rest on a player who still has lives.
    assert!(cur_player < lives.len(), "cur_player out of range");
    assert!(lives[cur_player] > 0, "it is a dead player's turn");
}

/// When the game reports a winner, that winner must have been alive going into
/// the final round.
fn check_win(lives_before: &[u32], winner: usize) {
    assert!(winner < lives_before.len(), "winner index out of range");
    assert!(
        lives_before[winner] > 0,
        "winner had no lives before the final round",
    );
}

fuzz_target!(|data: &[u8]| {
    let mut stream = ByteStream::new(data);

    // --- Decode the game configuration -------------------------------------
    let num_players = 2 + (stream.next() % 5) as u32; // 2..=6 players
    let lives = 1 + (stream.next() % 5) as u32; // 1..=5 lives each

    let mut seed = 0u64;
    for _ in 0..8 {
        seed = (seed << 8) | stream.next() as u64;
    }

    let mut game = Game::Stage2(State::<Stage2>::new(num_players, lives, seed));

    // Hard cap: the game must terminate in a bounded number of transitions.
    // Every resolved round removes a life, so a game can never legitimately run
    // this long; hitting the cap means the engine failed to make progress.
    let max_steps = (num_players * lives) as usize * 1000 + 1000;

    for _ in 0..max_steps {
        // Stop once the fuzzer's action script is used up.
        if stream.exhausted() {
            return;
        }

        game = match game {
            Game::Stage1(state) => {
                let lives_before: Vec<u32> = state.player_lives().to_vec();
                let prev_total: u32 = lives_before.iter().sum();

                let action = if stream.next() % 2 == 0 {
                    Stage1Action::Roll
                } else {
                    Stage1Action::Challenge
                };

                match state.apply_stage1_action(action) {
                    Stage1Result::NextStage(next) => {
                        check_invariants(next.player_lives(), next.cur_player().get(), prev_total);
                        Game::Stage2(next)
                    }
                    Stage1Result::Win(winner) => {
                        check_win(&lives_before, winner.get());
                        return;
                    }
                }
            }
            Game::Stage2(state) => {
                let lives_before: Vec<u32> = state.player_lives().to_vec();
                let prev_total: u32 = lives_before.iter().sum();

                let action = if stream.next() % 2 == 0 {
                    // Build a claim value from the next byte, clamped into range.
                    Stage2Action::Claim(Roll::from_value(stream.next() % (Roll::MAX + 1)))
                } else {
                    Stage2Action::Reroll
                };

                match state.apply_stage2_action(action) {
                    Stage2Result::NextTurn(next) => {
                        check_invariants(next.player_lives(), next.cur_player().get(), prev_total);
                        Game::Stage1(next)
                    }
                    Stage2Result::NewGame(next) => {
                        check_invariants(next.player_lives(), next.cur_player().get(), prev_total);
                        Game::Stage2(next)
                    }
                    Stage2Result::Win(winner) => {
                        check_win(&lives_before, winner.get());
                        return;
                    }
                }
            }
        };
    }

    // If we exhausted the step budget without a win despite still having input
    // to feed, the game failed to make progress — a termination bug.
    panic!("game did not terminate within {max_steps} steps");
});
