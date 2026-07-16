test *ARGS:
    cargo nextest run {{ARGS}}

alias t := test

fmt:
    cargo fmt

check STRICT="":
    cargo clippy --all --all-targets {{ if STRICT != "" { "-- -D warnings" } else { "" } }}
    cargo fmt --check --all
    just test

serve:
    cargo run --package server --bin server

alias s := serve
