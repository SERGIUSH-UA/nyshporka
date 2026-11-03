"""🗜 Ім'я файлу геометрії рядків — лише в одних дверях (`nyshporka.htr.layout`).

З 0.40.0 геометрія лежить стиснутою (`<стор>.lines.json.gz`), а старі прогони —
простою. Читач, що збирає ім'я руками (`d / f"{stem}.lines.json"`), на новому
прогоні мовчки бачить «рамок немає»: кроп не ріжеться, підсвітки рядка немає, а
повідомлення звинувачує «старий прогін». Тому літерал імені поза доступником
заборонено, а там, де без нього не можна, причину названо нижче.
"""
from __future__ import annotations

import ast
from pathlib import Path

from nyshporka.htr import layout as HL

SRC = Path(__file__).resolve().parents[1] / "src" / "nyshporka"

#: Де літерал дозволено, і чому.
ALLOWED = {
    # самі двері
    "htr/layout.py",
    # їдуть на бокс без пакета — дзеркало констант, збіг перевіряється нижче
    "htr/runner.py",
    "htr/cells_read.py",
    "train/guest/cut_runner.py",
    "htr/patches/kraken_lineage_verify.py",
    # формат пулу Супряги: у пакеті геометрія проста, бо так її чекають старі клієнти
    "share/bundle.py",
    "share/accept.py",
}


def _literals(tree: ast.AST) -> list[tuple[int, str]]:
    """Рядкові літерали коду, крім докстрінгів і голих рядків-коментарів."""
    bare: set[int] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            bare.add(id(node.value))
    out = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in bare):
            out.append((getattr(node, "lineno", 0), node.value))
    return out


def test_geometry_name_only_through_layout() -> None:
    bad = []
    for f in sorted(SRC.rglob("*.py")):
        rel = f.relative_to(SRC).as_posix()
        if rel in ALLOWED:
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for line, s in _literals(tree):
            # Ім'я будують літералом, що ним ЗАКІНЧУЄТЬСЯ (`f"{stem}.lines.json"`,
            # `glob("*.lines.json")`, `endswith(".lines.json")`); згадка у
            # повідомленні чи описі — ні.
            if s.endswith((".lines.json", ".lines.json.gz")):
                bad.append(f"{rel}:{line}: {s!r}")
    assert not bad, (
        "ім'я файлу геометрії зібрано руками — бери nyshporka.htr.layout "
        "(geometry_path / read_geometry / write_geometry / geometry_stems):\n"
        + "\n".join(bad))


def test_standalone_mirrors_match_layout() -> None:
    """Раннер і голос клітинок пишуть ту саму форму, що читають двері."""
    for rel in ("htr/runner.py", "htr/cells_read.py"):
        tree = ast.parse((SRC / rel).read_text(encoding="utf-8"))
        got = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                t = node.targets[0]
                if (isinstance(t, ast.Name) and t.id.startswith("GEOMETRY_")
                        and isinstance(node.value, ast.Constant)):
                    got[t.id] = node.value.value
        assert got.get("GEOMETRY_GZ_SUFFIX") == HL.GZ_SUFFIX, rel
        assert got.get("GEOMETRY_PLAIN_SUFFIX") == HL.PLAIN_SUFFIX, rel
        if "GEOMETRY_GZ_LEVEL" in got:
            assert got["GEOMETRY_GZ_LEVEL"] == HL.GZ_LEVEL, rel
