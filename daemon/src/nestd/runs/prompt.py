"""The paragraph that tells the agent about its folder's ports and dev server (B108)."""

from nestd.runs.blocks import PortBlock


def ports_prompt(block: PortBlock, command: str | None, listening: int | None) -> str:
    """`command` is the repo's run command, if it has one; `listening` the first port its
    run listens on as the agent's run opens, if it is running.
    """
    if block.size == 1:
        text = (
            f"This folder's port is {block.start}: NEST_PORT, also set in your environment. "
            "Use it for anything you start that listens on a port."
        )
    else:
        others = (
            "NEST_PORT_1 is the next one"
            if block.size == 2
            else f"NEST_PORT_1 to NEST_PORT_{block.size - 1} are the next ones"
        )
        text = (
            f"This folder's ports are {block.start} to {block.end}: NEST_PORT is "
            f"{block.start} and {others}, also set in your environment. Use them for "
            "anything you start that listens on a port."
        )
    if command is not None:
        text += (
            f" The project's dev server command is `{command}`; the user starts and stops it "
            "with the Run button."
        )
        if listening is not None:
            text += f" It is running and listening on http://localhost:{listening}."
    return text
