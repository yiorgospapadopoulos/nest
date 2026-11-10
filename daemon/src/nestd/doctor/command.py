"""The `nest` command: `nest doctor`, `nest doctor --report` and `nest uninstall`, and the
chat commands of `nestd.outside.command` (B151).

Separate from `nestd`, and light on purpose: it never starts the daemon or opens `AppContext`,
so it works when the daemon is down, which is when it is needed.
"""

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

from nestd.auth.devices import LOCAL_DEVICE_ACCOUNT
from nestd.auth.secrets import KeyringSecretStore
from nestd.config.errors import ConfigError
from nestd.config.loader import load_settings
from nestd.config.models import ServerSettings
from nestd.doctor.checks import by_rank, run_checks
from nestd.doctor.machine import Machine, this_machine
from nestd.doctor.models import Check
from nestd.doctor.report import write_report
from nestd.doctor.uninstall import NotAReleaseError, Uninstall
from nestd.outside.command import CHAT_COMMANDS, add_commands, run
from nestd.paths import AppPaths
from nestd.platform import current_platform

_MARKS = {"ok": "ok", "missing": "!!", "warning": " !", "not_applicable": " -"}


def machine_here() -> Machine:
    home = Path.home()
    system = current_platform()
    paths = AppPaths.from_env(os.environ, home, system)
    store = KeyringSecretStore(system.secret_store_help)
    try:
        port = load_settings(paths).server.port
    except ConfigError:
        port = ServerSettings().port

    def read_secret() -> None:
        store.get(LOCAL_DEVICE_ACCOUNT)

    return this_machine(paths, system, home, os.environ, port, read_secret)


def print_check(check: Check) -> None:
    detail = f"  {check.detail}" if check.detail else ""
    print(f"{_MARKS[check.state]} {check.title}{detail}")
    if check.message and check.state != "ok":
        print(f"   {check.message}")
    if check.fix is not None and check.state in ("missing", "warning"):
        print(f"   {'Run' if check.fix.kind == 'command' else 'Open'}: {check.fix.value}")


def doctor(machine: Machine, *, report: bool) -> int:
    if report:
        written = write_report(machine, datetime.now(UTC))
        print(written.text)
        print(f"Saved to {written.path}")
        print("Nothing was sent. Read it first. To report it, open this, add what happened")
        print("and attach the file or paste the report:")
        print(written.issue_url)
        return 0
    checks = by_rank(run_checks(machine))
    for check in checks:
        print_check(check)
    return 1 if any(check.state == "missing" for check in checks) else 0


def uninstall(machine: Machine, *, delete_data: bool) -> int:
    try:
        Uninstall(machine, print).run(delete_data=delete_data)
    except NotAReleaseError as error:
        print(f"nest: {error}", file=sys.stderr)
        return 1
    return 0


class _Parser(argparse.ArgumentParser):
    """Usage errors exit 1, as the chat commands' other failures do; 2 means a chat waits
    on the user (B151)."""

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: {message}\n")


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(prog="nest", description="Nest from the terminal")
    commands = parser.add_subparsers(required=True, dest="command", metavar="command")
    check = commands.add_parser("doctor", help="say what is wrong and how to fix it")
    check.add_argument("--report", action="store_true", help="write a bug report with no secrets")
    remove = commands.add_parser("uninstall", help="remove Nest, keeping your data")
    remove.add_argument(
        "--delete-data", action="store_true", help="also delete chats, settings and secrets"
    )
    add_commands(commands.add_parser)
    args = parser.parse_args(argv)
    if args.command in (*CHAT_COMMANDS, "mcp"):
        return run(args)
    machine = machine_here()
    if args.command == "doctor":
        return doctor(machine, report=args.report)
    return uninstall(machine, delete_data=args.delete_data)
