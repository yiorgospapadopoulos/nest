"""The list of checks, in the setup guide's order, then what only `nest doctor` adds."""

import platform as python_platform
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from importlib import metadata
from pathlib import Path

from nestd import __version__
from nestd.claude_code.cli import ClaudeLocations
from nestd.doctor.machine import Machine, json_object, system_line, within_limit
from nestd.doctor.models import Check, Fix
from nestd.release import install_line

_CODEX_PACKAGE = "openai-codex-cli-bin"
_LOW_DISK_BYTES = 2 * 1024**3
_MAC_TAILSCALE = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
_LINUX_PACKAGE_LINES = (
    ("apt-get", "sudo apt install {}"),
    ("dnf", "sudo dnf install {}"),
    ("pacman", "sudo pacman -S {}"),
    ("zypper", "sudo zypper install {}"),
)
_THE_APP_ANSWERS = "The app checks this."


def _package_line(machine: Machine, package: str) -> str:
    for manager, line in _LINUX_PACKAGE_LINES:
        if machine.which(manager):
            return line.format(package)
    return f"Install {package} with your distribution's package manager"


def _is_mac(machine: Machine) -> bool:
    return machine.platform.name == "macos"


def check_engine(machine: Machine) -> Check:
    """At least one: Claude Code or Codex signed in, or local models. Each user's own login."""
    found: list[str] = []
    env = machine.search_env
    locations = ClaudeLocations.default(machine.home, env, machine.platform)
    program = locations.standalone() or locations.bundled
    status = json_object(machine.command(str(program), "auth", "status", "--json").stdout)
    if status is not None and status.get("loggedIn") is True:
        found.append("Claude Code")
    codex_home = machine.paths.codex_home
    if codex_home is not None and (codex_home / "auth.json").is_file():
        found.append("Codex")
    if machine.database("SELECT 1 FROM local_models LIMIT 1") or machine.database(
        "SELECT 1 FROM local_settings WHERE key = 'local_only' AND value IN ('1', 'true')"
    ):
        found.append("Local models")
    if found:
        return Check(id="engine", title="Engine", state="ok", detail=", ".join(found))
    return Check(
        id="engine",
        title="Engine",
        state="missing",
        message="Nest needs one engine. Sign in to Claude Code or Codex, or use local models.",
    )


def check_git(machine: Machine) -> Check:
    title = "git"
    program = machine.which("git")
    # Apple's stub at /usr/bin/git opens an install dialog when run, so it is only looked at.
    stub = (
        _is_mac(machine)
        and program == "/usr/bin/git"
        and machine.command("xcode-select", "-p").returncode != 0
    )
    version = None if program is None or stub else machine.command(program, "--version")
    if version is not None and version.returncode == 0:
        return Check(id="git", title=title, state="ok", detail=version.stdout.split()[-1])
    command = "xcode-select --install" if _is_mac(machine) else _package_line(machine, "git")
    return Check(
        id="git",
        title=title,
        state="missing",
        message="Agents need git to work on your projects.",
        fix=Fix(kind="command", value=command),
    )


def check_github(machine: Machine) -> Check:
    title = "GitHub"
    program = machine.which("gh")
    if program is None:
        return Check(
            id="github",
            title=title,
            state="missing",
            message="Pull requests need GitHub's gh command.",
            fix=Fix(kind="link", value="https://cli.github.com"),
        )
    if machine.command(program, "auth", "status").returncode == 0:
        return Check(id="github", title=title, state="ok", detail="Signed in")
    return Check(
        id="github",
        title=title,
        state="missing",
        message="gh is installed but not signed in. Pull requests need it.",
        fix=Fix(kind="command", value="gh auth login"),
    )


def check_service(machine: Machine) -> Check:
    title = "Background service"
    status = machine.service.status()
    if status.installed and status.loaded and machine.healthy(machine.port):
        return Check(id="service", title=title, state="ok", detail="Starts at login")
    if machine.packaged:
        command = install_line(machine.env)
    else:
        command = "cd daemon && uv run nestd service install"
    what = "isn't answering" if status.loaded else "isn't running"
    return Check(
        id="service",
        title=title,
        state="missing",
        message=f"The background service {what}. This line repairs it and keeps your chats.",
        fix=Fix(kind="command", value=command),
    )


def _tailscale_program(machine: Machine) -> str | None:
    found = machine.which("tailscale")
    if found:
        return found
    return _MAC_TAILSCALE if _is_mac(machine) and Path(_MAC_TAILSCALE).is_file() else None


def _is_shared(serve_status: str, port: int) -> bool:
    return f"127.0.0.1:{port}" in serve_status or f"localhost:{port}" in serve_status


def check_tailscale(machine: Machine) -> Check:
    """Tailscale running, Nest shared on the tailnet, and a device that isn't this computer."""
    title = "Tailscale and iPhone"
    program = _tailscale_program(machine)
    if program is None:
        return Check(
            id="tailscale",
            title=title,
            state="missing",
            message="Your iPhone reaches Nest through Tailscale.",
            fix=Fix(kind="link", value="https://tailscale.com/download"),
        )
    status = json_object(machine.command(program, "status", "--json").stdout)
    if status is None or status.get("BackendState") != "Running":
        return Check(
            id="tailscale",
            title=title,
            state="missing",
            message="Tailscale is installed but not connected.",
            fix=Fix(kind="command", value="tailscale up"),
        )
    own = status.get("Self")
    name = own.get("DNSName") if isinstance(own, dict) else None
    host = name.rstrip(".") if isinstance(name, str) and name else None
    if not _is_shared(machine.command(program, "serve", "status", "--json").stdout, machine.port):
        return Check(
            id="tailscale",
            title=title,
            state="missing",
            message="Tailscale is running. Share Nest with your own devices.",
            detail=host,
            fix=Fix(kind="command", value=f"tailscale serve --bg {machine.port}"),
        )
    paired = machine.database(
        "SELECT 1 FROM devices WHERE is_local = 0 AND revoked_at IS NULL LIMIT 1"
    )
    if paired:
        return Check(id="tailscale", title=title, state="ok", detail=host)
    return Check(
        id="tailscale",
        title=title,
        state="missing",
        message="Nest is shared. Pair your iPhone.",
        detail=host,
    )


def check_notifications(machine: Machine) -> Check:
    """Only the app can ask: the system's answer on a Mac, a test notification on Linux."""
    return Check(
        id="notifications",
        title="Notifications",
        state="not_applicable",
        message=_THE_APP_ANSWERS,
    )


def check_ntfy(machine: Machine) -> Check:
    settings = machine.settings()
    ntfy = None if settings is None else settings.notifications.ntfy
    if ntfy is not None and ntfy.enabled and ntfy.topic:
        return Check(id="ntfy", title="ntfy", state="ok", detail=ntfy.server)
    return Check(id="ntfy", title="ntfy", state="not_applicable", detail="Optional")


def check_dictation(machine: Machine) -> Check:
    if not _is_mac(machine):
        return Check(id="dictation", title="Dictation", state="not_applicable")
    return Check(
        id="dictation", title="Dictation", state="not_applicable", message=_THE_APP_ANSWERS
    )


def check_secret_service(machine: Machine) -> Check:
    title = "Secret Service"
    if _is_mac(machine):
        return Check(id="secret_service", title=title, state="not_applicable")
    failure = within_limit(machine.read_secret)
    if failure is None:
        return Check(id="secret_service", title=title, state="ok")
    return Check(
        id="secret_service",
        title=title,
        state="missing",
        message=machine.platform.secret_store_help,
    )


def check_first_chat(machine: Machine) -> Check:
    if machine.database("SELECT 1 FROM sessions LIMIT 1"):
        return Check(id="first_chat", title="First chat", state="ok")
    return Check(id="first_chat", title="First chat", state="missing")


def check_engine_installs(machine: Machine) -> Check:
    """The engines Nest runs: Claude Code from the user or the Agent SDK, Codex from a package."""
    locations = ClaudeLocations.default(machine.home, machine.search_env, machine.platform)
    claude = locations.standalone() or locations.bundled
    try:
        codex = metadata.version(_CODEX_PACKAGE)
    except metadata.PackageNotFoundError:
        codex = None
    if claude.is_file() and codex is not None:
        detail = f"Claude Code {locations.bundled_version}, Codex {codex}"
        return Check(id="engine_installs", title="Engine installs", state="ok", detail=detail)
    return Check(
        id="engine_installs",
        title="Engine installs",
        state="missing",
        message="An engine's files are missing. Installing Nest again brings them back.",
        fix=Fix(kind="command", value=install_line(machine.env)),
    )


def check_port(machine: Machine) -> Check:
    title = "Port"
    if machine.healthy(machine.port):
        return Check(id="port", title=title, state="ok", detail=str(machine.port))
    return Check(
        id="port",
        title=title,
        state="warning",
        message=f"Nothing answers as Nest on port {machine.port}. Check the service's log.",
        detail=str(machine.paths.logs_dir / "daemon.log"),
    )


def check_disk(machine: Machine) -> Check:
    title = "Disk space"
    folder = machine.paths.data_dir if machine.paths.data_dir.exists() else machine.home
    free = machine.disk_free(folder)
    detail = f"{free / 1024**3:.1f} GB free"
    if free >= _LOW_DISK_BYTES:
        return Check(id="disk", title=title, state="ok", detail=detail)
    return Check(
        id="disk",
        title=title,
        state="warning",
        message="Agents and updates need more room than this.",
        detail=detail,
    )


def check_versions(machine: Machine) -> Check:
    python = python_platform.python_version()
    return Check(
        id="versions",
        title="Versions",
        state="ok",
        detail=f"Nest {__version__}, Python {python}, {system_line()}",
    )


def check_permissions(machine: Machine) -> Check:
    if not _is_mac(machine):
        return Check(id="permissions", title="Mac permissions", state="not_applicable")
    return Check(
        id="permissions",
        title="Mac permissions",
        state="not_applicable",
        message=_THE_APP_ANSWERS,
    )


type CheckFunction = Callable[[Machine], Check]

CHECKS: tuple[CheckFunction, ...] = (
    check_engine,
    check_git,
    check_github,
    check_service,
    check_tailscale,
    check_notifications,
    check_ntfy,
    check_dictation,
    check_secret_service,
    check_first_chat,
    check_engine_installs,
    check_port,
    check_disk,
    check_versions,
    check_permissions,
)


def run_checks(machine: Machine) -> list[Check]:
    """Every check, side by side so one slow command does not hold up the list."""

    def run(check: CheckFunction) -> Check:
        return check(machine)

    with ThreadPoolExecutor(max_workers=len(CHECKS), thread_name_prefix="nest-check") as pool:
        return list(pool.map(run, CHECKS))
