use engine::state::{Roll, Stage1Action, Stage1Result, Stage2Action, Stage2Result, State};

fn main() {
    println!("Hello, world!");
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct PlayerId(u32);

#[derive(Clone, Debug)]
struct Turn {}

#[derive(Clone, Debug)]
struct History {}

struct ClientHandler;

impl ClientHandler {
    pub async fn get_stage1_action(
        &mut self,
        _player_id: PlayerId,
        _history: &History,
    ) -> Stage1Action {
        // Placeholder implementation
        todo!()
    }

    pub async fn get_stage2_action(
        &mut self,
        _player_id: PlayerId,
        _roll: Roll,
        _stage1_action: Option<Stage1Action>,
        _history: &History,
    ) -> Stage2Action {
        // Placeholder implementation
        todo!()
    }
}

async fn run_game(
    player_ids: Vec<PlayerId>,
    num_lives: u32,
    dice_seed: u64,
    client_handler: &mut ClientHandler,
) -> PlayerId {
    let mut state = State::new(player_ids.len(), num_lives, dice_seed);
    let history = History {};

    let mut stage1_action = None;

    loop {
        let player_action = client_handler
            .get_stage2_action(
                player_ids[state.cur_player().get()].clone(),
                state.roll(),
                stage1_action.take(),
                &history,
            )
            .await;
        state = match state.apply_stage2_action(player_action) {
            Stage2Result::NextTurn(state) => {
                let player_action = client_handler
                    .get_stage1_action(player_ids[state.cur_player().get()].clone(), &history)
                    .await;
                stage1_action = Some(player_action);
                match state.apply_stage1_action(player_action) {
                    Stage1Result::NextStage(state) => state,
                    Stage1Result::Win(player_index) => {
                        return player_ids[player_index.get()].clone();
                    }
                }
            }
            Stage2Result::NewGame(state) => state,
            Stage2Result::Win(player_index) => return player_ids[player_index.get()].clone(),
        }
    }
}
