import json
import os
import subprocess
from pathlib import Path

from harness.claude_sessions.live import LiveChats, pid_alive
from tests.claude_support import CHAT_A, CHAT_B, ClaudeHome


def test_pid_alive_checks_the_process() -> None:
    finished = subprocess.Popen(["true"])  # noqa: S607
    finished.wait()

    assert pid_alive(os.getpid()) is True
    assert pid_alive(1) is True  # launchd: alive, though not ours to signal
    assert pid_alive(finished.pid) is False


def test_running_reads_live_session_files(tmp_path: Path) -> None:
    home = ClaudeHome(tmp_path)
    home.open_chat(10, CHAT_A, entrypoint="cli")
    home.open_chat(11, CHAT_A, entrypoint="sdk-py")
    home.open_chat(12, CHAT_B)
    home.open_chat(0, CHAT_B)
    sessions = home.sessions
    (sessions / "13.json").write_text(json.dumps({"pid": 13, "sessionId": CHAT_B}), "utf-8")
    (sessions / "14.json").write_text("{broken", encoding="utf-8")
    (sessions / "15.json").write_text("[15]", encoding="utf-8")
    (sessions / "16.json").write_text(json.dumps({"pid": "16", "sessionId": CHAT_B}), "utf-8")
    (sessions / "17.json").write_text(json.dumps({"pid": 17}), encoding="utf-8")
    (sessions / "18.abc.key").write_text("secret", encoding="utf-8")
    (sessions / "x.json").write_text(json.dumps({"pid": 19, "sessionId": CHAT_B}), "utf-8")

    live = LiveChats(tmp_path, alive=lambda pid: pid in {10, 11, 13, 16, 17, 19})

    assert live.running() == {CHAT_A: ["cli", "sdk-py"], CHAT_B: [""]}


def test_open_elsewhere_ignores_harnesss_own_sdk_run(tmp_path: Path) -> None:
    home = ClaudeHome(tmp_path)
    home.open_chat(20, CHAT_A, entrypoint="sdk-py")
    home.open_chat(21, CHAT_B, entrypoint="claude-vscode")
    live = LiveChats(tmp_path, alive=lambda _pid: True)

    assert live.open_elsewhere(CHAT_A, own_run=False) is True
    assert live.open_elsewhere(CHAT_A, own_run=True) is False
    assert live.open_elsewhere(CHAT_B, own_run=True) is True
    assert live.open_elsewhere("unknown", own_run=False) is False


def test_nothing_is_open_without_a_claude_dir(tmp_path: Path) -> None:
    assert LiveChats(None).running() == {}
    assert LiveChats(tmp_path / "missing").running() == {}
