test *ARGS:
    cargo nextest run {{ARGS}}

alias t := test

fuzz MAX_TIME="":
    cd engine && cargo +nightly-2026-02-24 fuzz run play_game {{ if MAX_TIME != "" { "-- -max_total_time=" + MAX_TIME } else { "" } }}

fmt:
    cargo fmt

check STRICT="":
    cargo clippy --all --all-targets {{ if STRICT != "" { "-- -D warnings" } else { "" } }}
    cargo fmt --check --all
    # The fuzz crate is a separate workspace, so lint and format it explicitly.
    cd engine/fuzz && cargo +nightly-2026-02-24 clippy --all-targets {{ if STRICT != "" { "-- -D warnings" } else { "" } }}
    cd engine/fuzz && cargo +nightly-2026-02-24 fmt --check
    cd engine && cargo +nightly-2026-02-24 fuzz build play_game
    just test

push BRANCH:
    jj git fetch
    jj bookmark move {{BRANCH}} --to=@-
    jj git push
