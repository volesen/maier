"""Python implementation of the maier dice game.

- `maier.engine` — the game rules state machine
- `maier.server` — TCP game server hosting lobbies of the game
- `maier.client` — library for writing clients/bots (see `maier.client`'s
  docstring for a minimal example)
"""

from beartype.claw import beartype_this_package

beartype_this_package()
