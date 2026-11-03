"""A run's output buffer and the listening ports lsof reports (B108)."""

import logging
from functools import partial
from pathlib import Path

import pytest

from nestd.platform import LINUX, MACOS
from nestd.runs.listening import listening_ports, parse_ports, port_probe, proc_listening_ports
from nestd.runs.output import OutputBuffer


def test_the_buffer_keeps_the_last_lines_and_a_line_that_goes_on() -> None:
    buffer = OutputBuffer(max_lines=3)

    first = buffer.add(b"one\ntwo\nthr")
    buffer.add(b"ee\nfour\n")
    buffer.add(b"")
    buffer.add(b"fi")

    assert first == "one\ntwo\nthr"
    assert buffer.text() == "three\nfour\nfi"


def test_the_buffer_keeps_escapes_and_decodes_split_characters() -> None:
    buffer = OutputBuffer()
    euro = "€".encode()

    texts = [buffer.add(b"\x1b[32mready\x1b[0m " + euro[:2]), buffer.add(euro[2:] + b"\xff\n")]

    assert texts == ["\x1b[32mready\x1b[0m ", "€�\n"]
    assert buffer.text() == "\x1b[32mready\x1b[0m €�\n"


def test_clearing_the_buffer_starts_afresh() -> None:
    buffer = OutputBuffer()
    buffer.add(b"old \xe2\x82")

    buffer.clear()
    buffer.add_text("$ npm run dev\n")

    assert buffer.text() == "$ npm run dev\n"


def test_lsof_name_lines_give_unique_ascending_ports() -> None:
    output = "p123\nf20\nn*:41021\nf21\nn127.0.0.1:41020\nf22\nn[::1]:41020\nnodd:name\nn*:*\n"

    assert parse_ports(output) == [41020, 41021]
    assert parse_ports("") == []


def fake_lsof(tmp_path: Path, script: str) -> Path:
    lsof = tmp_path / "lsof"
    lsof.write_text(f"#!/bin/sh\n{script}\n", encoding="utf-8")
    lsof.chmod(0o755)
    return lsof


async def test_listening_ports_asks_lsof_about_the_process_group(tmp_path: Path) -> None:
    args = tmp_path / "args"
    lsof = fake_lsof(tmp_path, f'echo "$@" > {args}\nprintf "p1\\nf3\\nn*:41022\\n"\nexit 1')

    ports = await listening_ports(4242, lsof)

    assert ports == [41022]
    assert args.read_text(encoding="utf-8") == "-nP -a -g 4242 -iTCP -sTCP:LISTEN -Fn\n"


async def test_lsof_missing_or_hanging_means_no_ports(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    hanging = fake_lsof(tmp_path, "exec sleep 30")

    with caplog.at_level(logging.WARNING):
        missing = await listening_ports(1, tmp_path / "nope")
        slow = await listening_ports(1, hanging, time_limit=0.05)

    assert (missing, slow) == ([], [])
    assert "could not run lsof" in caplog.text
    assert "lsof took longer than 0.05s" in caplog.text


# B117: Ubuntu keeps lsof in /usr/bin, and a Linux box may have none at all.
TCP_HEADER = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when uid inode\n"


def tcp_line(local: str, state: str, inode: int) -> str:
    return (
        f"   0: {local} 00000000:0000 {state} 00000000:00000000 00:00000000 00000000"
        f"  1000        0 {inode} 1 0 0\n"
    )


def fake_process(proc: Path, pid: int, group: int, inodes: list[int]) -> None:
    folder = proc / str(pid)
    (folder / "fd").mkdir(parents=True)
    # A name with spaces and parentheses, as a process may have.
    stat = f"{pid} (node (dev) x) S 1 {group} {group} 0 -1\n"
    (folder / "stat").write_text(stat, encoding="utf-8")
    for fd, inode in enumerate(inodes, start=3):
        (folder / "fd" / str(fd)).symlink_to(f"socket:[{inode}]")
    (folder / "fd" / "0").symlink_to("/dev/null")


async def test_without_lsof_linux_reads_the_groups_listening_sockets_from_proc(
    tmp_path: Path,
) -> None:
    proc = tmp_path / "proc"
    fake_process(proc, 100, 4242, [501, 502])
    fake_process(proc, 101, 4242, [504])
    fake_process(proc, 200, 9999, [601])
    (proc / "self").mkdir()
    (proc / "net").mkdir()
    (proc / "net" / "tcp").write_text(
        TCP_HEADER
        # 127.0.0.1:41000 listening; an established socket; another group's 8080.
        + tcp_line("0100007F:A028", "0A", 501)
        + tcp_line("0100007F:A029", "01", 502)
        + tcp_line("00000000:1F90", "0A", 601),
        encoding="utf-8",
    )
    (proc / "net" / "tcp6").write_text(
        TCP_HEADER + tcp_line("00000000000000000000000001000000:A02A", "0A", 504),
        encoding="utf-8",
    )

    assert await proc_listening_ports(4242, proc) == [41000, 41002]
    assert await proc_listening_ports(1, tmp_path / "missing") == []


def test_the_probe_finds_lsof_where_the_system_keeps_it() -> None:
    def which(name: str, path: str | None = None) -> str | None:
        assert path == "/home/me/.local/bin:/usr/bin"
        return "/usr/bin/lsof" if name == "lsof" else None

    def nowhere(_name: str, path: str | None = None) -> str | None:
        return None

    linux = port_probe(LINUX, "/home/me/.local/bin:/usr/bin", which)

    assert isinstance(linux, partial)
    assert linux.keywords == {"lsof": Path("/usr/bin/lsof")}
    assert port_probe(LINUX, "/usr/bin", nowhere) is proc_listening_ports
    # macOS keeps lsof at /usr/sbin/lsof, as before.
    assert port_probe(MACOS, "", which) is listening_ports
