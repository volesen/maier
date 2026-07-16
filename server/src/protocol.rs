use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "action", rename_all = "snake_case")]
pub enum Action {
    Roll,
    Challenge,
    Claim { rank: u8 },
    Reroll,
}

#[derive(Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ClientMessage {
    Join { name: String },
    Act { request_id: String, action: Action },
}

#[derive(Serialize)]
pub struct PlayerInfo {
    pub id: String,
    pub name: String,
}

/// Everything a player is allowed to observe, sent with every turn request.
#[derive(Serialize)]
pub struct State {
    pub you: String,
    pub round: u32,
    /// Rank of your hidden roll, 1 (3-2) to 21 (Meyer), once you have rolled.
    pub my_roll: Option<u8>,
    pub current_claim: Option<u8>,
    pub claimant: Option<String>,
    pub lives: BTreeMap<String, u8>,
    pub turn_order: Vec<String>,
    pub rerolled: bool,
}

#[derive(Serialize)]
#[serde(tag = "event", rename_all = "snake_case")]
pub enum Event {
    Rolled {
        player: String,
    },
    Rerolled {
        player: String,
    },
    Claimed {
        player: String,
        rank: u8,
    },
    Challenged {
        challenger: String,
        claimant: String,
    },
    Reveal {
        claimant: String,
        actual: u8,
        claimed: u8,
        loser: String,
        lives_lost: u8,
    },
    Eliminated {
        player: String,
    },
}

#[derive(Serialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ServerMessage {
    Welcome {
        player_id: String,
    },
    GameStart {
        players: Vec<PlayerInfo>,
        lives: u8,
    },
    RoundStart {
        round: u32,
        starting_player: String,
    },
    Turn {
        request_id: String,
        state: State,
        legal_actions: Vec<Action>,
    },
    Event(Event),
    GameEnd {
        winner: String,
    },
}
