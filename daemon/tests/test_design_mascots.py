from pathlib import Path

import pytest

from nestd.design.errors import DesignError
from nestd.design.mascots import load_mascots, render_swift, render_ts
from nestd.design.outputs import generate, render_outputs
from tests.design_support import REPO_ROOT, minimal_tokens, write_mascots, write_tokens

ROOT = Path(__file__).resolve().parents[2]
NAMES = [
    "bluebell",
    "dragonfly",
    "moth",
    "firefly",
    "rose",
    "frost",
    "sprig",
    "nightshade",
    "brook",
    "star",
]
GRID = ["." * 14] * 14


def _write(path: Path, colors: str, **sprites: list[str]) -> Path:
    tables = "".join(
        f"[mascots.{name}]\nrows = {rows!r}\n".replace("'", '"') for name, rows in sprites.items()
    )
    path.write_text(f"colors = {colors}\n{tables}")
    return path


def _all_but(name: str, **changed: list[str]) -> dict[str, list[str]]:
    """The shipped sprites in order, with some replaced and `name` dropped."""
    shipped = load_mascots(ROOT / "design" / "mascots.toml").sprites
    return {
        key: changed.get(key, list(rows))
        for key, rows in shipped.items()
        if key != name or key in changed
    }


def test_the_shipped_file_has_ten_valid_mascots() -> None:
    mascots = load_mascots(ROOT / "design" / "mascots.toml")

    assert list(mascots.sprites) == NAMES
    assert len(mascots.colors) == 10
    for rows in mascots.sprites.values():
        assert len(rows) == 14
        assert all(len(row) == 14 and set(row) <= set(".#+o*ek") for row in rows)
        assert sum(len(row) - row.count(".") for row in rows) >= 30
        assert any("e" in row for row in rows)


def test_bad_grids_are_refused(tmp_path: Path) -> None:
    path = tmp_path / "m.toml"
    path.write_text('colors = ["#000000"]\n[mascots.bluebell]\nrows = ["#"]\n')

    with pytest.raises(ValueError, match="bluebell"):
        load_mascots(path)


def test_a_bad_row_is_named(tmp_path: Path) -> None:
    sprites = _all_but("bluebell", bluebell=[GRID[0], "...x...e......", *GRID[:12]])
    path = _write(tmp_path / "m.toml", '["#000000"]', **sprites)

    with pytest.raises(ValueError, match=r"bluebell.*row 2.*\.#\+o\*ek"):
        load_mascots(path)


def test_a_short_row_is_named(tmp_path: Path) -> None:
    sprites = _all_but("moth", moth=[*GRID[:13], "#e."])
    path = _write(tmp_path / "m.toml", '["#000000"]', **sprites)

    with pytest.raises(ValueError, match=r"moth.*row 14.*14 characters"):
        load_mascots(path)


def test_the_mascot_names_are_fixed(tmp_path: Path) -> None:
    sprites = _all_but("bluebell")
    path = _write(tmp_path / "m.toml", '["#000000"]', **sprites)

    with pytest.raises(ValueError, match="bluebell"):
        load_mascots(path)


def test_the_mascot_order_is_fixed(tmp_path: Path) -> None:
    shipped = _all_but("none")
    swapped = {"dragonfly": shipped["dragonfly"], "bluebell": shipped["bluebell"]}
    sprites = {**swapped, **{k: v for k, v in shipped.items() if k not in swapped}}
    path = _write(tmp_path / "m.toml", '["#000000"]', **sprites)

    with pytest.raises(ValueError, match="in that order"):
        load_mascots(path)


def test_a_mascot_without_eyes_is_refused(tmp_path: Path) -> None:
    eyeless = [row.replace("e", "o") for row in _all_but("none")["star"]]
    path = _write(tmp_path / "m.toml", '["#000000"]', **_all_but("star", star=eyeless))

    with pytest.raises(ValueError, match=r"star.*eye"):
        load_mascots(path)


def test_every_drawn_cell_counts_as_filled(tmp_path: Path) -> None:
    """Shade, light, wing and ink cells count, not only the body colour: exactly 30 here."""
    sparse = ["ok*+" * 3 + "..", "ee" + "." * 12, "o" * 14, "kk" + "." * 12, *GRID[:10]]
    path = _write(tmp_path / "m.toml", '["#000000"]', **_all_but("brook", brook=sparse))

    assert load_mascots(path).sprites["brook"] == tuple(sparse)


def test_a_sparse_mascot_is_refused(tmp_path: Path) -> None:
    # 29 drawn cells, one short.
    sprites = _all_but("bluebell", bluebell=["e" * 14, "#" * 14, "+" + "." * 13, *GRID[:11]])
    path = _write(tmp_path / "m.toml", '["#000000"]', **sprites)

    with pytest.raises(ValueError, match=r"bluebell.*30"):
        load_mascots(path)


def test_bad_colours_are_refused(tmp_path: Path) -> None:
    path = _write(tmp_path / "m.toml", '["red"]', **_all_but("none"))

    with pytest.raises(ValueError, match="red"):
        load_mascots(path)


def test_the_file_must_exist_and_parse(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not found"):
        load_mascots(tmp_path / "missing.toml")
    broken = tmp_path / "broken.toml"
    broken.write_text("colors = [")
    with pytest.raises(ValueError, match="invalid TOML"):
        load_mascots(broken)
    empty = tmp_path / "empty.toml"
    empty.write_text('colors = ["#000000"]\n')
    with pytest.raises(ValueError, match="mascots"):
        load_mascots(empty)


def test_outputs_are_generated() -> None:
    mascots = load_mascots(ROOT / "design" / "mascots.toml")

    ts = render_ts(mascots)
    swift = render_swift(mascots)

    assert "export const MASCOT_SPRITES" in ts
    assert '"bluebell": [' in ts
    assert "public enum MascotSprites" in swift
    assert '"#8B7CF6"' in ts
    assert '"#8B7CF6"' in swift
    assert "export const PIXIE_COLORS" in ts
    assert 'import type { Mascot } from "../api/types.ts";' in ts
    assert "export type Mascot" not in ts
    assert "public enum PixieColors" in swift


def test_outputs_carry_the_generated_header() -> None:
    mascots = load_mascots(ROOT / "design" / "mascots.toml")

    assert render_ts(mascots).startswith("// Generated by `nestd design generate` from design/")
    assert render_swift(mascots).startswith("// Generated by `nestd design generate` from design/")


def test_generate_writes_the_mascot_files(tmp_path: Path) -> None:
    write_tokens(tmp_path, minimal_tokens())
    write_mascots(tmp_path)

    written = generate(tmp_path)

    assert Path("web/src/generated/mascots.ts") in written
    assert Path("apple/Sources/NestKit/Generated/Mascots.swift") in written
    assert set(render_outputs(REPO_ROOT)) >= set(written)


def test_a_missing_mascot_file_is_a_design_error(tmp_path: Path) -> None:
    write_tokens(tmp_path, minimal_tokens())

    with pytest.raises(DesignError, match=r"mascots\.toml"):
        generate(tmp_path)


def test_a_mascot_needs_fourteen_rows(tmp_path: Path) -> None:
    sprites = _all_but("dragonfly", dragonfly=[*GRID[:13]])
    path = _write(tmp_path / "m.toml", '["#000000"]', **sprites)

    with pytest.raises(ValueError, match=r"dragonfly.*14 rows"):
        load_mascots(path)


def test_outputs_export_the_ink_and_tones() -> None:
    """B89: both clients draw each cell code from the one colour with the same tones."""
    mascots = load_mascots(ROOT / "design" / "mascots.toml")

    ts = render_ts(mascots)
    swift = render_swift(mascots)

    assert 'export const MASCOT_INK = "#221E29";' in ts
    assert "export const MASCOT_TONES = {" in ts
    assert '  shade: { toward: "#000000", amount: 0.3, opacity: 1 },' in ts
    assert '  light: { toward: "#FFFFFF", amount: 0.7, opacity: 1 },' in ts
    assert '  wing: { toward: "#FFFFFF", amount: 0.45, opacity: 0.85 },' in ts
    assert "14 columns by 14 rows" in ts
    assert 'public static let ink = "#221E29"' in swift
    assert "public struct MascotTone: Sendable, Equatable {" in swift
    assert (
        'public static let shade = MascotTone(toward: "#000000", amount: 0.3, opacity: 1)' in swift
    )
    assert (
        'public static let wing = MascotTone(toward: "#FFFFFF", amount: 0.45, opacity: 0.85)'
        in swift
    )
    assert "14 columns by 14 rows" in swift
