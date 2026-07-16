# Meyer bot client

A minimal Python client for the Meyer server. A bot is a function
`decide(state, legal_actions) -> action` — the server tells you exactly
which actions are legal, so the simplest valid bot picks one at random:

```python
import random

from client import run
from client.types import Action, State


def decide(state: State, legal: list[Action]) -> Action:
    return random.choice(legal)


run(decide, name="my-bot", host="127.0.0.1", port=5000)
```

Run a built-in baseline against a server:

```sh
uv run client [bot] [--name X] [--host H] [--port P] [--threshold T]
```

Baselines, roughly in order of strength:

- `random` — picks any legal action; the floor.
- `honest` — never challenges or rerolls, lies as little as possible.
- `minimal` — always claims the smallest legal rank, regardless of its roll.
- `paranoid` — challenges whenever legal. Punishes over-claimers.
- `cutoff` — challenges iff P(a fresh roll makes the claim) < `--threshold`.
- `statistician` — `cutoff`, plus rerolls whenever it would otherwise have to lie.

The wire protocol is newline-delimited JSON over TCP; see `src/client/types.py`
for the message shapes. Rolls and claims are plain ranks from 1 (3-2, the
lowest roll) to 21 (Meyer) — the protocol never mentions dice, so comparing
rolls and claims is just integer comparison. Pair ranks (14-19) have
probability 1/36 each; every other rank has probability 2/36.
