"""The report is shared in public by people who won't read every line, so nothing that
identifies or unlocks anything may survive, wherever it turns up in a log.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from nestd.doctor.machine import Machine
from nestd.doctor.report import redact, write_report
from nestd.paths import AppPaths
from nestd.platform import MACOS
from nestd.service.base import CommandResult, ServiceStatus

HOME = Path("/Users/alice")


@pytest.mark.parametrize(
    ("line", "secret"),
    [
        ("token gho_16C7e42F292c6912E7710c838347Ae178B4a used", "gho_16C7"),
        ("ghp_abcdefghijklmnopqrstuvwxyz0123456789 ok", "ghp_abc"),
        ("github_pat_11ABCDE0Y0abcdefghij_klmnop", "github_pat"),
        ("key sk-ant-api03-abcDEF123456789 rejected", "sk-ant"),
        ("sk-proj-abcdefgh12345678", "sk-proj"),
        ("xoxb-1234-5678-abcdefgh", "xoxb"),
        ("AIzaSyA1234567890abcdefghijkl", "AIzaSy"),
        ("Authorization: Bearer abc.def-ghi", "abc.def-ghi"),
        ("authorization=Basic dXNlcjpwYXNz", "dXNlcjpwYXNz"),
        ("https://x-access-token:hunter2@github.com/me/repo.git", "hunter2"),
        ("postgres://bob:pw@db.internal:5432/app", "bob:pw"),
        ('{"api_key": "abc123"}', "abc123"),
        ("password=swordfish&next=1", "swordfish"),
        ("GET /api/events?token=Q2xhdWRl HTTP/1.1", "Q2xhdWRl"),
        ("session_token: 8f3a9c", "8f3a9c"),
        ("tokens=8f3a9c", "8f3a9c"),
        ("api_key_v2: abc123", "abc123"),
        ('{\\"password\\": \\"hunter2\\"}', "hunter2"),
        ('password="two words here"', "words"),
        ("password='two words here'", "words"),
        ("run --token abc123 --verbose", "abc123"),
        ("run --api-key=abc123", "abc123"),
        ("Cookie: a=1; session=abc123; theme=dark", "abc123"),
        ("Set-Cookie: sid=abc123; Path=/; HttpOnly", "abc123"),
        ("https://user:p@ss/word@example.com/x", "p@ss"),
        ("QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVowMTIzNDU2Nzg5Ky8=", "QUJDREVGR0hJ"),
        ("cookie=sid-1234", "sid-1234"),
        ("from alice.smith+nest@example.co.uk at 10:00", "alice.smith"),
        ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.c2lnbmF0dXJl", "eyJhbGci"),
        ("device 2mH8qk7Zf3nLxV9pTbR4cJ6wYdE1sUaG0oNiKyQeXhM stored", "2mH8qk7Z"),
        ("0123456789abcdef0123456789abcdef01234567", "0123456789abcdef"),
        ("shared at alice-air.tail3f2a.ts.net", "alice-air"),
        ("/Users/alice/Library/Application Support/nest/daemon.log", "alice"),
        ("/home/bob/.config/nest/settings.toml", "bob"),
        ("worktree /Users/someone-else/nest", "someone-else"),
    ],
)
def test_nothing_private_survives(line: str, secret: str) -> None:
    assert secret not in redact(line, HOME)


def test_what_helps_with_a_bug_stays() -> None:
    line = "2026-11-07 00:39:37,753 INFO uvicorn.error: Uvicorn running on http://127.0.0.1:8765"

    assert redact(line, HOME) == line


class Service:
    unit_path = Path("/nowhere")

    def install(self) -> None: ...

    def remove_legacy(self) -> bool:
        return False

    def stop(self) -> None: ...

    def uninstall(self) -> None: ...

    def status(self) -> ServiceStatus:
        return ServiceStatus(installed=False, loaded=False, detail="")


def test_the_report_file_holds_the_checks_and_a_clean_log(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    paths = AppPaths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
    paths.logs_dir.mkdir(parents=True)
    log = f"ERROR at {home}/projects/x with token=abc123 for me@example.com\n"
    (paths.logs_dir / "daemon.log").write_text(log, encoding="utf-8")

    def nothing(_args: object, _env: object, _limit: float = 1.0) -> CommandResult:
        return CommandResult(1, "", "")

    def down(_port: int) -> bool:
        return False

    def no_secret() -> None:
        return None

    machine = Machine(
        paths=paths,
        platform=MACOS,
        home=home,
        env={"PATH": ""},
        port=8765,
        service=Service(),
        read_secret=no_secret,
        packaged=True,
        run=nothing,
        healthy=down,
    )

    report = write_report(machine, datetime(2026, 11, 7, tzinfo=UTC))

    text = Path(report.path).read_text(encoding="utf-8")
    assert text == report.text
    assert "[missing] Background service" in text
    assert "~/projects/x" in text
    assert "abc123" not in text
    assert "me@example.com" not in text
    assert oct(Path(report.path).stat().st_mode)[-3:] == "600"
