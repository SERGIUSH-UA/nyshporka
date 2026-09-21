"""Що НЕ мусить виїхати в пакеті обміну.

🔴 Найдорожча помилка цього модуля не в тому, що пакет не зібрався, а в тому,
що він зібрався й забрав зайве. Тека прогону сусідить із дослідженням, а мета
несе шлях машини, а в ньому звичайно стоїть ім'я користувача — тобто публікація
декоду публікує заодно ім'я автора й розкладку його диска.

Ці ворота ловлять саме повернення такого регресу: перелік членів архіву проти
білого списку плюс пошук домашнього шляху в маніфесті й у меті.
"""
from __future__ import annotations

import json
import tarfile
from pathlib import Path

import pytest
from _share import SECRET_CASE_DIR, make_run, manifest_for

from nyshporka.share import bundle

#: Те, що лежить поруч у теці прогону й не має стосунку до тексту.
NOISE = {
    "_rescue_crops": "0001-l12.png",
    "_claims": "shard-3.json",
    "_drain": "queue.json",
    "logs": "run.log",
}


@pytest.fixture
def space(tmp_path: Path):
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    yield tmp_path
    W.reset()


def _dirty_run(root: Path) -> Path:
    run = make_run(root, "spr-8433")
    for sub, name in NOISE.items():
        d = run / sub
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_bytes(b"x" * 64)
    (run / "_htr_quarantine.json").write_text("[]", encoding="utf-8")
    return run


def test_only_text_and_meta_travel(space: Path, tmp_path: Path) -> None:
    run = _dirty_run(space / "reports" / "htr")
    m = manifest_for([bundle.voice_of(run)])
    dest = tmp_path / "pack.nyshtext"
    bundle.write(dest, m, [run])

    with tarfile.open(dest) as tar:
        names = tar.getnames()
    inside_runs = [n for n in names if n.startswith("runs/")]
    for n in inside_runs:
        tail = n.rsplit("/", 1)[-1]
        assert tail.endswith(".txt") or tail == bundle.META_NAME, n
    for sub in NOISE:
        assert not [n for n in names if f"/{sub}/" in n], sub
    assert not [n for n in names if "quarantine" in n]


def test_case_dir_is_stripped_from_meta(space: Path, tmp_path: Path) -> None:
    """Шлях машини не переживає пакування — ні в меті, ні деінде в архіві."""
    run = make_run(space / "reports" / "htr", "spr-8433")
    raw = json.loads((run / bundle.META_NAME).read_text(encoding="utf-8"))
    assert raw["case_dir"] == SECRET_CASE_DIR   # передумова тесту, не перевірка

    m = manifest_for([bundle.voice_of(run)])
    dest = tmp_path / "pack.nyshtext"
    bundle.write(dest, m, [run])

    with tarfile.open(dest) as tar:
        for member in tar.getmembers():
            src = tar.extractfile(member)
            if src is None:
                continue
            body = src.read().decode("utf-8", errors="replace")
            assert SECRET_CASE_DIR not in body, member.name
            assert "Petrenka" not in body, member.name
            assert "case_dir" not in body, member.name


def test_meta_keeps_what_the_receiver_needs(space: Path, tmp_path: Path) -> None:
    """Чистка не мусить з'їдати модель і ключ: без них пакет марний."""
    run = make_run(space / "reports" / "htr", "spr-8433")
    raw = json.loads((run / bundle.META_NAME).read_text(encoding="utf-8"))
    clean = bundle.clean_meta(raw)
    assert clean["model"] == "pysar_cyr_v17.pt"
    assert clean["case_key"] == "DAHMO/315/8433"
    assert clean["frames_total"] == 3
    assert "case_dir" not in clean


def test_gates_refuse_a_manifest_with_machine_fields() -> None:
    """Якщо чистку колись обійдуть, ворота мусять це побачити."""
    from nyshporka.share import gates

    m = manifest_for([], pages=3, frames=3)
    m.decode["voices"] = [{"run": "r", "model": "m.pt", "pages": 3}]
    m.decode["case_dir"] = SECRET_CASE_DIR
    v = gates.check(m)
    assert not v.passed
    assert any("case_dir" in r for r in v.refusals)


@pytest.mark.parametrize("evil", [
    "runs/../../evil.txt",
    "runs/spr/../../../evil.txt",
    r"runs/out/..\..\evil.txt",
])
def test_extract_refuses_to_escape(tmp_path: Path, evil: str) -> None:
    """Пакет приїхав від незнайомця — іменам у ньому віри стільки ж, скільки
    орендованому боксу. Гард той самий, що в хмарного забору."""
    import io

    pack = tmp_path / "evil.nyshtext"
    with tarfile.open(pack, "w:gz") as tar:
        blob = b"shkoda"
        info = tarfile.TarInfo(evil)
        info.size = len(blob)
        tar.addfile(info, io.BytesIO(blob))

    out = tmp_path / "taken"
    bundle.extract(pack, out)
    assert not list(tmp_path.glob("evil.txt"))
    assert not list(tmp_path.parent.glob("evil.txt"))
