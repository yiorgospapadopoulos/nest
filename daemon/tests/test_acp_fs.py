"""The file reads and writes an ACP engine asks Nest for (B107)."""

from pathlib import Path

import pytest

from nestd.providers.acp_fs import AcpFiles
from nestd.providers.acp_permissions import AcpRules
from nestd.providers.acp_rpc import AcpRpcError


def files(tmp_path: Path, write_root: Path | None = None) -> AcpFiles:
    rules = AcpRules("default", guarded=False, folders=(tmp_path / "repo",), write_root=write_root)
    return AcpFiles(lambda: rules)


async def test_a_read_is_served_inside_the_chats_folders_only(tmp_path: Path) -> None:
    (tmp_path / "repo").mkdir()
    (tmp_path / "repo" / "a.txt").write_text("one\ntwo\nthree\n")
    (tmp_path / "secret.txt").write_text("key")
    served = files(tmp_path)

    lines = await served.read({"path": str(tmp_path / "repo" / "a.txt"), "line": 2, "limit": 1})

    assert lines == {"content": "two\n"}
    with pytest.raises(AcpRpcError):
        await served.read({"path": str(tmp_path / "secret.txt")})
    with pytest.raises(AcpRpcError):
        await served.read({"path": str(tmp_path / "repo" / ".." / "secret.txt")})


async def test_a_write_outside_the_write_root_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "pixie"
    served = files(tmp_path, write_root=root)

    await served.write({"path": str(root / "notes" / "a.md"), "content": "kept"})

    assert (root / "notes" / "a.md").read_text() == "kept"
    with pytest.raises(AcpRpcError):
        await served.write({"path": str(tmp_path / "repo" / "a.md"), "content": "no"})
    assert not (tmp_path / "repo" / "a.md").exists()
