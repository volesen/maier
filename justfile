test *ARGS:
    cargo nextest run {{ARGS}}

alias t := test

fuzz MAX_TIME="":
    cd server && cargo +nightly-2026-02-24 fuzz run play_game {{ if MAX_TIME != "" { "-- -max_total_time=" + MAX_TIME } else { "" } }}

fmt:
    cargo fmt

check STRICT="":
    cargo clippy --all --all-targets {{ if STRICT != "" { "-- -D warnings" } else { "" } }}
    cargo fmt --check --all
    just test

serve:
    cargo run --package server --bin server

alias s := serve

push BRANCH:
    jj git fetch
    jj bookmark move {{BRANCH}} --to=@-
    jj git push
