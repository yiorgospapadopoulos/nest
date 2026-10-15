import os
import signal

from nestd.service.restart import terminate_self


def test_terminate_self_sends_sigterm_to_this_process() -> None:
    sent: list[tuple[int, int]] = []

    terminate_self(kill=lambda pid, sig: sent.append((pid, sig)))

    assert sent == [(os.getpid(), signal.SIGTERM)]
