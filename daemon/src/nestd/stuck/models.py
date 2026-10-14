from datetime import datetime
from typing import Literal

from pydantic import BaseModel

# waiting: on a permission prompt, question or plan; silent: running without output;
# repeating: the same tool call over and over; long_turn: one turn running very long.
type StuckReason = Literal["waiting", "silent", "repeating", "long_turn"]


class StuckFlag(BaseModel):
    reason: StuckReason
    # When the condition began: the prompt, the last output, the first repeated call, or
    # the turn's start.
    since: datetime
    # One sentence for people, such as "Called Bash 5 times in a row with the same input".
    details: str
