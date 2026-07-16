mod game;
mod protocol;

use std::io::{BufRead, BufReader, ErrorKind, Write};
use std::net::{TcpListener, TcpStream};
use std::time::{Duration, Instant};

use rand::RngExt;

use protocol::{Action, ClientMessage, Event, PlayerInfo, ServerMessage, State};

const LIVES: u8 = 6;
const DEFAULT_TURN_DEADLINE_MS: u64 = 5000;
const JOIN_DEADLINE: Duration = Duration::from_secs(10);

struct Client {
    id: String,
    name: String,
    reader: BufReader<TcpStream>,
    writer: TcpStream,
}

impl Client {
    fn send(&mut self, msg: &ServerMessage) {
        let mut line = serde_json::to_string(msg).expect("serialize");
        line.push('\n');
        // A dead connection just means this player times out on their turns.
        let _ = self.writer.write_all(line.as_bytes());
    }
}

fn main() {
    let mut args = std::env::args().skip(1);
    let port: u16 = args.next().map_or(5000, |a| a.parse().expect("port"));
    let num_players: usize = args
        .next()
        .map_or(2, |a| a.parse().expect("number of players"));
    let deadline_ms: u64 = args.next().map_or(DEFAULT_TURN_DEADLINE_MS, |a| {
        a.parse().expect("deadline ms")
    });

    let listener = TcpListener::bind(("0.0.0.0", port)).expect("bind");
    eprintln!("listening on port {port}, waiting for {num_players} players");

    let mut clients = Vec::new();
    while clients.len() < num_players {
        let Ok((stream, addr)) = listener.accept() else {
            continue;
        };
        match accept_join(stream, clients.len()) {
            Ok(client) => {
                eprintln!("{} joined as {} from {addr}", client.name, client.id);
                clients.push(client);
            }
            Err(err) => eprintln!("rejected connection from {addr}: {err}"),
        }
    }

    Game::new(clients, Duration::from_millis(deadline_ms)).run();
}

fn accept_join(stream: TcpStream, seat: usize) -> std::io::Result<Client> {
    stream.set_read_timeout(Some(JOIN_DEADLINE))?;
    stream.set_nodelay(true)?;
    let writer = stream.try_clone()?;
    let mut reader = BufReader::new(stream);
    let mut line = String::new();
    reader.read_line(&mut line)?;
    let msg = serde_json::from_str(&line).map_err(std::io::Error::other)?;
    let ClientMessage::Join { name } = msg else {
        return Err(std::io::Error::new(ErrorKind::InvalidData, "expected join"));
    };
    let mut client = Client {
        id: format!("p{seat}"),
        name,
        reader,
        writer,
    };
    client.send(&ServerMessage::Welcome {
        player_id: client.id.clone(),
    });
    Ok(client)
}

struct Game {
    clients: Vec<Client>,
    lives: Vec<u8>,
    round: u32,
    next_request_id: u64,
    turn_deadline: Duration,
    rng: rand::rngs::ThreadRng,
}

impl Game {
    fn new(clients: Vec<Client>, turn_deadline: Duration) -> Self {
        let lives = vec![LIVES; clients.len()];
        Self {
            clients,
            lives,
            round: 0,
            next_request_id: 0,
            turn_deadline,
            rng: rand::rng(),
        }
    }

    fn run(&mut self) {
        let players = self
            .clients
            .iter()
            .map(|c| PlayerInfo {
                id: c.id.clone(),
                name: c.name.clone(),
            })
            .collect();
        self.broadcast(&ServerMessage::GameStart {
            players,
            lives: LIVES,
        });

        let mut starter = 0;
        while self.lives.iter().filter(|&&l| l > 0).count() > 1 {
            starter = self.play_round(starter);
        }

        let winner = self.lives.iter().position(|&l| l > 0).unwrap();
        eprintln!(
            "game over after {} rounds, winner: {}",
            self.round, self.clients[winner].name
        );
        self.broadcast(&ServerMessage::GameEnd {
            winner: self.id(winner),
        });
    }

    /// Plays one round (ends with a challenge); returns who starts the next round.
    fn play_round(&mut self, starter: usize) -> usize {
        self.round += 1;
        self.broadcast(&ServerMessage::RoundStart {
            round: self.round,
            starting_player: self.id(starter),
        });

        let mut current_claim: Option<u8> = None;
        let mut claimant: Option<(usize, u8)> = None;
        let mut turn = starter;
        loop {
            let stage1 = match current_claim {
                None => vec![Action::Roll],
                Some(game::MEYER) => vec![Action::Challenge],
                Some(_) => vec![Action::Roll, Action::Challenge],
            };
            let act = self.request(turn, None, false, current_claim, claimant, &stage1);
            if act == Action::Challenge {
                let (cl, actual) = claimant.unwrap();
                return self.resolve_challenge(turn, cl, actual, current_claim.unwrap());
            }

            let mut roll = game::roll(&mut self.rng);
            self.broadcast(&ServerMessage::Event(Event::Rolled {
                player: self.id(turn),
            }));
            let mut rerolled = false;
            let rank = loop {
                let min = current_claim.map_or(1, |c| c + 1);
                let mut legal: Vec<Action> = (min..=game::MEYER)
                    .map(|rank| Action::Claim { rank })
                    .collect();
                if !rerolled {
                    legal.push(Action::Reroll);
                }
                match self.request(turn, Some(roll), rerolled, current_claim, claimant, &legal) {
                    Action::Reroll => {
                        rerolled = true;
                        roll = game::roll(&mut self.rng);
                        self.broadcast(&ServerMessage::Event(Event::Rerolled {
                            player: self.id(turn),
                        }));
                    }
                    Action::Claim { rank } => break rank,
                    _ => unreachable!("not in legal actions"),
                }
            };
            current_claim = Some(rank);
            claimant = Some((turn, roll));
            self.broadcast(&ServerMessage::Event(Event::Claimed {
                player: self.id(turn),
                rank,
            }));
            turn = self.next_alive(turn);
        }
    }

    fn resolve_challenge(
        &mut self,
        challenger: usize,
        claimant: usize,
        actual: u8,
        claimed: u8,
    ) -> usize {
        self.broadcast(&ServerMessage::Event(Event::Challenged {
            challenger: self.id(challenger),
            claimant: self.id(claimant),
        }));
        let loser = if actual >= claimed {
            challenger
        } else {
            claimant
        };
        let lives_lost = if actual == game::MEYER { 2 } else { 1 };
        self.lives[loser] = self.lives[loser].saturating_sub(lives_lost);
        self.broadcast(&ServerMessage::Event(Event::Reveal {
            claimant: self.id(claimant),
            actual,
            claimed,
            loser: self.id(loser),
            lives_lost,
        }));
        if self.lives[loser] == 0 {
            self.broadcast(&ServerMessage::Event(Event::Eliminated {
                player: self.id(loser),
            }));
            // Loser is out; the challenge's survivor starts the next round.
            if loser == challenger {
                claimant
            } else {
                challenger
            }
        } else {
            loser
        }
    }

    /// Asks a player to pick one of `legal`; falls back to a random legal
    /// action on timeout, disconnect, or invalid reply.
    fn request(
        &mut self,
        p: usize,
        my_roll: Option<u8>,
        rerolled: bool,
        current_claim: Option<u8>,
        claimant: Option<(usize, u8)>,
        legal: &[Action],
    ) -> Action {
        self.next_request_id += 1;
        let request_id = self.next_request_id.to_string();
        let state = State {
            you: self.id(p),
            round: self.round,
            my_roll,
            current_claim,
            claimant: claimant.map(|(i, _)| self.id(i)),
            lives: self
                .clients
                .iter()
                .zip(&self.lives)
                .map(|(c, &l)| (c.id.clone(), l))
                .collect(),
            turn_order: self.clients.iter().map(|c| c.id.clone()).collect(),
            rerolled,
        };
        self.clients[p].send(&ServerMessage::Turn {
            request_id: request_id.clone(),
            state,
            legal_actions: legal.to_vec(),
        });

        let deadline = Instant::now() + self.turn_deadline;
        let client = &mut self.clients[p];
        let mut line = String::new();
        loop {
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                break;
            }
            let _ = client.reader.get_ref().set_read_timeout(Some(remaining));
            line.clear();
            match client.reader.read_line(&mut line) {
                Ok(0) => break, // disconnected
                Ok(_) => {
                    if let Ok(ClientMessage::Act {
                        request_id: rid,
                        action,
                    }) = serde_json::from_str(&line)
                        && rid == request_id
                        && legal.contains(&action)
                    {
                        return action;
                    }
                    // Stale, malformed, or illegal reply: keep waiting.
                }
                Err(e) if matches!(e.kind(), ErrorKind::WouldBlock | ErrorKind::TimedOut) => break,
                Err(_) => break,
            }
        }
        let action = legal[self.rng.random_range(0..legal.len())].clone();
        eprintln!(
            "{}: no valid reply, autoplaying {action:?}",
            self.clients[p].id
        );
        action
    }

    fn broadcast(&mut self, msg: &ServerMessage) {
        for client in &mut self.clients {
            client.send(msg);
        }
    }

    fn next_alive(&self, from: usize) -> usize {
        let n = self.clients.len();
        (1..=n)
            .map(|k| (from + k) % n)
            .find(|&i| self.lives[i] > 0)
            .unwrap()
    }

    fn id(&self, p: usize) -> String {
        self.clients[p].id.clone()
    }
}
