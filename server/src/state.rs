use std::marker::PhantomData;

use rand::{
    SeedableRng,
    distr::{Distribution, Uniform},
};

type Rng = rand_chacha::ChaCha20Rng;

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct Roll {
    value: u8,
}

pub struct Dice {
    rng: Rng,
    uniform: Uniform<u8>,
}

impl Dice {
    pub fn new(seed: u64) -> Self {
        Self {
            rng: Rng::seed_from_u64(seed),
            uniform: Uniform::new(0, 21).unwrap(),
        }
    }

    pub fn roll(&mut self) -> Roll {
        Roll {
            value: self.uniform.sample(&mut self.rng),
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Stage1Action {
    Roll,
    Challenge,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Stage2Action {
    Claim(Roll),
    Reroll,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct PlayerIndex(usize);
pub struct Turn {
    stage1: Stage1Action,
    revealed_roll: Option<Roll>,
    stage2: Option<Stage2Action>,
}

pub struct History {
    turns: Vec<Turn>,
}

pub struct Stage1;
pub struct Stage2;

pub trait Stage {}

impl Stage for Stage1 {}
impl Stage for Stage2 {}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Claim {
    claim: Roll,
    claimer: PlayerIndex,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct CurrentRoll {
    roll: Roll,
    roller: PlayerIndex,
}

impl CurrentRoll {
    pub fn create(dice: &mut Dice, roller: PlayerIndex) -> Self {
        Self {
            roll: dice.roll(),
            roller,
        }
    }
}

pub struct State<S: Stage> {
    dice: Dice,
    cur_roll: CurrentRoll,
    newest_claim: Option<Claim>,
    reroll: bool,
    cur_player: PlayerIndex,
    player_lives: Vec<u32>,
    _phantom: PhantomData<S>,
}

impl<S: Stage> State<S> {
    fn next_player(&self) -> Option<PlayerIndex> {
        // Find first player with lives left after current player
        let num_players = self.player_lives.len();
        let mut next = (self.cur_player.0 + 1) % num_players;
        while self.player_lives[next] == 0 {
            next = (next + 1) % num_players;
            if next == self.cur_player.0 {
                // All players are out of lives, return current player
                return None;
            }
        }
        Some(PlayerIndex(next))
    }

    fn switch_to_next_player(&mut self) {
        self.cur_player = self
            .next_player()
            .expect("No other players have lives. Should have been caught elsewhere.");
    }

    fn new_roll(&mut self) -> CurrentRoll {
        CurrentRoll::create(&mut self.dice, self.cur_player)
    }

    #[must_use]
    fn end_game(&mut self, loser: PlayerIndex) -> Option<PlayerIndex> {
        self.player_lives[loser.0] -= 1;
        // Check if there is only one player left with lives and return that player if so
        let alive_players: Vec<PlayerIndex> = self
            .player_lives
            .iter()
            .copied()
            .enumerate()
            .filter(|&(_, lives)| lives > 0)
            .map(|(index, _)| PlayerIndex(index))
            .collect();
        if alive_players.len() == 1 {
            return Some(alive_players[0]);
        }
        if loser == self.cur_player {
            self.switch_to_next_player();
            self.cur_roll = self.new_roll();
        } else {
            self.cur_roll = self.new_roll();
        }
        self.newest_claim = None;
        self.reroll = false;
        None
    }
}

pub enum Stage1Result {
    NextStage(State<Stage2>),
    Win(PlayerIndex),
}

impl State<Stage1> {
    fn from_stage2(state: State<Stage2>) -> Self {
        State::<Stage1> {
            dice: state.dice,
            cur_roll: state.cur_roll,
            newest_claim: state.newest_claim,
            reroll: state.reroll,
            cur_player: state.cur_player,
            player_lives: state.player_lives,
            _phantom: PhantomData::<Stage1>,
        }
    }

    pub fn apply_stage1_action(mut self, action: Stage1Action, roller: &mut Dice) -> Stage1Result {
        let newest_claim = self
            .newest_claim
            .expect("If there is no claim, stage 1 should be skipped.");
        if self.reroll {
            match action {
                Stage1Action::Roll => {
                    self.cur_roll = self.new_roll();
                    self.reroll = false;
                }
                Stage1Action::Challenge => {
                    let loser = if self.cur_roll.roll > newest_claim.claim {
                        // Challenger loses a life.
                        self.cur_player
                    } else {
                        // Previous player loses a life.
                        self.cur_roll.roller
                    };
                    if let Some(loser) = self.end_game(loser) {
                        return Stage1Result::Win(loser);
                    }
                }
            }
        } else {
            match action {
                Stage1Action::Roll => {
                    self.cur_roll = self.new_roll();
                }
                Stage1Action::Challenge => {
                    let loser = if self.cur_roll.roll == newest_claim.claim {
                        // Challenger loses a life
                        self.cur_player
                    } else {
                        // Claimer loses a life
                        newest_claim.claimer
                    };
                    if let Some(loser) = self.end_game(loser) {
                        return Stage1Result::Win(loser);
                    }
                }
            }
        }
        Stage1Result::NextStage(State::<Stage2> {
            dice: self.dice,
            cur_roll: self.cur_roll,
            newest_claim: self.newest_claim,
            reroll: self.reroll,
            cur_player: self.cur_player,
            player_lives: self.player_lives,
            _phantom: PhantomData::<Stage2>,
        })
    }
}

pub enum Stage2Result {
    NextTurn(State<Stage1>),
    NewGame(State<Stage2>),
    Win(PlayerIndex),
}

impl State<Stage2> {
    pub fn new(num_players: u32, player_lives: u32, dice_seed: u64) -> Self {
        let mut dice = Dice::new(dice_seed);
        let cur_roll = CurrentRoll::create(&mut dice, PlayerIndex(0));
        State {
            dice,
            cur_roll,
            newest_claim: None,
            reroll: false,
            cur_player: PlayerIndex(0),
            player_lives: vec![player_lives; num_players as usize],
            _phantom: PhantomData::<_>,
        }
    }

    pub fn apply_stage2_action(mut self, action: Stage2Action) -> Stage2Result {
        assert!(
            !self.reroll,
            "Rerolls be started in the previous player's stage 2, so cannot still be active in stage 2."
        );
        if let Some(Claim {
            claim: cur_claim,
            claimer: _,
        }) = self.newest_claim
        {
            match action {
                Stage2Action::Claim(claimed_roll) => {
                    if claimed_roll <= cur_claim {
                        // When it's current player that loses, this always moves to next player.
                        if let Some(winner) = self.end_game(self.cur_player) {
                            Stage2Result::Win(winner)
                        } else {
                            Stage2Result::NewGame(self)
                        }
                    } else {
                        self.newest_claim = Some(Claim {
                            claim: claimed_roll,
                            claimer: self.cur_player,
                        });
                        self.switch_to_next_player();
                        Stage2Result::NextTurn(State::from_stage2(self))
                    }
                }
                Stage2Action::Reroll => {
                    self.reroll = true;
                    self.cur_roll = self.new_roll();
                    self.switch_to_next_player();
                    Stage2Result::NextTurn(State::from_stage2(self))
                }
            }
        } else {
            match action {
                Stage2Action::Claim(roll) => {
                    self.newest_claim = Some(Claim {
                        claim: roll,
                        claimer: self.cur_player,
                    });
                    self.switch_to_next_player();
                    Stage2Result::NextTurn(State::from_stage2(self))
                }
                Stage2Action::Reroll => {
                    if let Some(winner) = self.end_game(self.cur_player) {
                        Stage2Result::Win(winner)
                    } else {
                        Stage2Result::NewGame(self)
                    }
                }
            }
        }
    }
}
