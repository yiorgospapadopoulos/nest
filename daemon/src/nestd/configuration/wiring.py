"""How the configuration page learns what is not in the engines' files (B97): the
accounts and versions from Nest's engine services, Claude's plugins and connectors.
"""

from collections.abc import Callable
from pathlib import Path

from nestd.claude_code.account import ClaudeAccount
from nestd.claude_code.cli import ClaudeCli, ClaudeCliError
from nestd.claude_code.extensions import Extensions
from nestd.config.models import ConfigurationSettings
from nestd.configuration.engines import (
    CodexLocations,
    EngineAccount,
    EngineProbe,
    Versions,
    account_label,
    codex_versions,
)
from nestd.configuration.models import Standalone
from nestd.configuration.service import Sources
from nestd.connectors.registry import ConnectorRegistry
from nestd.engine.codex import CodexEngine
from nestd.gitops.runner import CommandRunner
from nestd.repos.service import RepoService


def build_sources(
    *,
    claude_account: ClaudeAccount,
    claude_cli: ClaudeCli,
    codex: CodexEngine,
    codex_locations: CodexLocations,
    run: CommandRunner,
    cwd: Path,
    extensions: Extensions,
    connectors: ConnectorRegistry,
    repos: RepoService,
    settings: Callable[[], ConfigurationSettings],
    save_settings: Callable[[ConfigurationSettings], ConfigurationSettings],
) -> Sources:
    async def claude() -> EngineAccount:
        try:
            status = await claude_account.status()
        except ClaudeCliError:
            return EngineAccount(signed_in=None)
        return EngineAccount(status.signed_in, account_label(status.email, status.plan))

    async def claude_versions() -> Versions:
        status = await claude_cli.status()
        standalone = (
            None if status.path is None else Standalone(path=status.path, version=status.version)
        )
        return Versions(status.bundled_version, standalone)

    async def codex_account() -> EngineAccount:
        status = await codex.status()
        account = status.account
        label = None if account is None else account_label(account.email, account.plan)
        return EngineAccount(status.signed_in, label)

    async def codex_version() -> Versions:
        return await codex_versions(codex_locations, run, cwd)

    async def plugin_folders() -> list[tuple[str, Path]]:
        try:
            return await extensions.plugin_folders()
        except ClaudeCliError:
            return []

    async def claude_ai_connectors() -> int:
        listed = await connectors.list_connectors()
        return sum(1 for connector in listed if connector.group == "claude.ai")

    return Sources(
        claude=EngineProbe(claude, claude_versions),
        codex=EngineProbe(codex_account, codex_version),
        plugin_folders=plugin_folders,
        connectors=claude_ai_connectors,
        settings=settings,
        save_settings=save_settings,
        repo_paths=lambda: [repo.path for repo in repos.list_repos()],
    )
