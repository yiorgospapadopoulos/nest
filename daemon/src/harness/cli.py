"""Command line entry point.

`harness serve | service install|uninstall|status | pair | design generate|check`.
"""

import argparse
import asyncio
from collections.abc import Callable
from pathlib import Path

from harness.api.app import create_app
from harness.auth.models import PairingCode
from harness.config.errors import ConfigError
from harness.context import AppContext
from harness.design.errors import DesignError
from harness.design.loader import find_root
from harness.design.outputs import generate, stale_outputs
from harness.logging_setup import configure_logging
from harness.paths import AppPaths
from harness.runtime import Runtime, default_runtime
from harness.service.launchd import LaunchdService, ServiceError, build_path_env
from harness.storage.errors import DatabaseError

type Handler = Callable[[argparse.Namespace, AppPaths, Runtime], int]


def main(argv: list[str] | None = None, runtime: Runtime | None = None) -> int:
    rt = runtime or default_runtime()
    args = _parser().parse_args(argv)
    handler: Handler = args.handler
    try:
        return handler(args, AppPaths.from_env(rt.env, rt.home), rt)
    except (ConfigError, DatabaseError, DesignError, ServiceError) as error:
        print(f"harness: {error}", file=rt.err)
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harness", description="harness daemon")
    commands = parser.add_subparsers(required=True, metavar="command")

    serve = commands.add_parser("serve", help="run the daemon in the foreground")
    serve.add_argument("--port", type=int, help="override the port from settings.toml")
    serve.set_defaults(handler=_serve)

    service = commands.add_parser("service", help="manage the launchd service")
    actions = service.add_subparsers(required=True, metavar="action")
    for name, handler, help_text in (
        ("install", _service_install, "install and start the service"),
        ("uninstall", _service_uninstall, "stop and remove the service"),
        ("status", _service_status, "show whether the service is installed and loaded"),
    ):
        actions.add_parser(name, help=help_text).set_defaults(handler=handler)

    pair = commands.add_parser("pair", help="create a one-time code to pair a device")
    pair.set_defaults(handler=_pair)

    design = commands.add_parser("design", help="generate the client design token files")
    design_actions = design.add_subparsers(required=True, metavar="action")
    for name, handler, help_text in (
        ("generate", _design_generate, "write the CSS, Swift and mascot files from design/"),
        ("check", _design_check, "fail if the generated token files are missing or stale"),
    ):
        action = design_actions.add_parser(name, help=help_text)
        action.add_argument("--root", type=Path, help="repository root (default: found upward)")
        action.set_defaults(handler=handler)
    return parser


def _serve(args: argparse.Namespace, paths: AppPaths, rt: Runtime) -> int:
    configure_logging(rt.err)
    asyncio.run(_run_server(paths, rt, args.port))
    return 0


async def _run_server(paths: AppPaths, rt: Runtime, port: int | None) -> None:
    ctx = await AppContext.build(paths, rt.secrets, rt.clock)
    try:
        await rt.serve(create_app(ctx), port if port is not None else ctx.settings.server.port)
    finally:
        await ctx.close()


def _launchd(paths: AppPaths, rt: Runtime) -> LaunchdService:
    return LaunchdService(
        paths=paths,
        launch_agents_dir=rt.home / "Library" / "LaunchAgents",
        uid=rt.uid,
        runner=rt.run_command,
        program_args=[rt.executable, "-m", "harness", "serve"],
        path_env=build_path_env(rt.home),
    )


def _service_install(_args: argparse.Namespace, paths: AppPaths, rt: Runtime) -> int:
    service = _launchd(paths, rt)
    service.install()
    print(f"Installed and started {service.plist_path.stem} ({service.plist_path})", file=rt.out)
    print(f"Logs: {paths.logs_dir / 'daemon.log'}", file=rt.out)
    return 0


def _service_uninstall(_args: argparse.Namespace, paths: AppPaths, rt: Runtime) -> int:
    service = _launchd(paths, rt)
    service.uninstall()
    print(f"Stopped and removed {service.plist_path.stem}", file=rt.out)
    return 0


def _service_status(_args: argparse.Namespace, paths: AppPaths, rt: Runtime) -> int:
    status = _launchd(paths, rt).status()
    print(f"installed: {'yes' if status.installed else 'no'}", file=rt.out)
    print(f"loaded: {'yes' if status.loaded else 'no'}", file=rt.out)
    print(status.detail.rstrip(), file=rt.out)
    return 0 if status.loaded else 1


def _pair(_args: argparse.Namespace, paths: AppPaths, rt: Runtime) -> int:
    code = asyncio.run(_create_pairing_code(paths, rt))
    print(f"Pairing code: {code.code}", file=rt.out)
    print(f"Expires at {code.expires_at.astimezone():%H:%M:%S} (local time)", file=rt.out)
    return 0


async def _create_pairing_code(paths: AppPaths, rt: Runtime) -> PairingCode:
    ctx = await AppContext.build(paths, rt.secrets, rt.clock)
    try:
        return await ctx.devices.create_pairing_code()
    finally:
        await ctx.close()


def _design_root(args: argparse.Namespace) -> Path:
    root: Path | None = args.root
    return root if root is not None else find_root(Path.cwd())


def _design_generate(args: argparse.Namespace, _paths: AppPaths, rt: Runtime) -> int:
    for path in generate(_design_root(args)):
        print(f"Wrote {path}", file=rt.out)
    return 0


def _design_check(args: argparse.Namespace, _paths: AppPaths, rt: Runtime) -> int:
    problems = stale_outputs(_design_root(args))
    if not problems:
        print("Design tokens are up to date", file=rt.out)
        return 0
    for problem in problems:
        print(f"harness: {problem}", file=rt.err)
    print("harness: run `harness design generate` to update them", file=rt.err)
    return 1
