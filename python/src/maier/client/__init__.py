"""Client library for the Meyer game server.

A client is a function `decide(state, legal_actions) -> action` — the server
says exactly which actions are legal, so the simplest valid client picks one
at random:

```python
import random

from maier.client import run
from maier.client.types import Action, State


def decide(state: State, legal: list[Action]) -> Action:
    return random.choice(legal)


run(decide, name="my-bot")
```

See `maier.client.types` for the message shapes and the hooks `run()` accepts
(`on_event` / `on_message` listeners, lobby selection, starting the game).
"""

from maier.client.run import run as run
