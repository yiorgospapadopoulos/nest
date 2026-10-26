"""A run's output buffer and the listening ports lsof reports (B108)."""

import logging
from pathlib import Path

import pytest

from nestd.runs.listening import listening_ports, parse_ports
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
