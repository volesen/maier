"""TCP game server speaking the Meyer wire protocol, driven by the `engine` package."""

from beartype.claw import beartype_this_package

beartype_this_package()

from server.game import main as main  # noqa: E402
