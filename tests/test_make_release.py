"""📦 Реліз ваг складається з чинних паків і не чіпає замінених.

Замінені паки лежать у своєму релізі (`weights-v1`), і їх качають і старі версії
застосунку, і нова — як запасний голос. Скрипт, що вимагав би їхні файли чи
переписав би їм тег, або не склав би новий реліз, або зламав би старий.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "make_release.py"
MANIFEST = ROOT / "src" / "nyshporka" / "setup" / "data" / "packs.json"


def _packs() -> list[dict]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["packs"]


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True,
                          text=True, encoding="utf-8", check=False)


def test_release_needs_only_current_packs(tmp_path: Path) -> None:
    current = [p for p in _packs() if not p.get("superseded")]
    assert current, "у маніфесті немає чинних паків"
    for p in current:
        (tmp_path / p["filename"]).write_bytes(b"x")
    before = MANIFEST.read_bytes()
    res = _run(str(tmp_path), "--release", "weights-test", "--dry-run")
    assert res.returncode == 0, res.stdout + res.stderr
    assert MANIFEST.read_bytes() == before
    for p in _packs():
        if p.get("superseded"):
            assert p["id"] not in res.stdout, f"замінений пак {p['id']} потрапив у реліз"


def test_current_packs_carry_hashes() -> None:
    """Порожній sha256 у чинному паку робить `nysh models get` мертвим."""
    for p in _packs():
        if not p.get("superseded"):
            assert p["sha256"] and p["size"], p["id"]


def test_one_current_pack_per_role() -> None:
    """Один чинний пак на (письмо, рушій): інакше вибір моделі вирішує номер версії."""
    roles = [(p["script"], p["engine"]) for p in _packs()
             if p["kind"] == "model" and not p.get("superseded")]
    assert len(roles) == len(set(roles)), roles
