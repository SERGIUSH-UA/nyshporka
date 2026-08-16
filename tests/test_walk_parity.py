"""🚶 Обхід `cases.walk` віддає рівно те саме, що чотири `glob`-и до нього.

Порядок обходу тут — не косметика. Споживачі (`library._scan_disk_cases`,
`collect._ordered_cases`, `collect._unfiled_material`) тримають `seen` і стелю
`limit=4000`: інший порядок дав би інший ЗРІЗ бібліотеки, а не просто інший темп.
І помилка була б тиха — просто інші справи в реєстрі.

Три пастки, які тут закріплені, бо на кожній легко послизнутись (усі три
перевірені на цій машині):

1. **`sorted(Path)` на Windows регістронечутливе** — `alpha` йде ПЕРЕД `Beta`.
   `sorted(str(...))` дав би зворотний порядок.
2. **`pathlib.glob` бачить приховані теки** (на відміну від модуля `glob`).
3. **`glob("*/*")` заходить у теки з `_` на початку** — перевірка
   `name.startswith("_")` у споживачів дивиться лише на ОСТАННІЙ сегмент.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

# 🔴 Імпорт відкладений тією самою причиною, що в `test_register_and_notes`:
# `cases/__init__` тягне `library`, а той кличе `workspace()` на рівні модуля,
# тобто вимагає налаштованого простору ще на етапі ЗБОРУ тестів. Сам `walk`
# від простору не залежить узагалі — він приймає корені аргументом.
walk_root: Any = None

_SKIP = frozenset({"periodika"})


@pytest.fixture(autouse=True)
def _walk_module(tmp_path_factory):
    global walk_root
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path_factory.mktemp("ws"), name="тест",
                      origin="test"))
    from nyshporka.cases.walk import walk_root as _wr

    walk_root = _wr
    yield
    W.reset()


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """Дерево з усіма межовими випадками, які трапляються в `data/raw`."""
    def touch(rel: str, data: bytes = b"x") -> None:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    # різний регістр — ловить сортування рядками замість Path
    touch("alpha/0001.jpg")
    touch("Beta/0001.JPG")
    touch("Beta/скан.pdf")
    # прихована тека — pathlib.glob її бачить
    touch(".hidden/0001.png")
    # тека з `_` на початку: сама пропускається споживачем, але ВСЕРЕДИНУ заходимо
    touch("_drafts/real_case/0001.jpg")
    # чотири рівні — межа max_depth
    touch("anrm/villages/Пиржота/2086525_1-40/0001.jpg")
    # п'ятий рівень — за межею, не має з'явитись
    touch("anrm/villages/Пиржота/2086525_1-40/crops/x.jpg")
    # skip-slug обрізається піддеревом
    touch("periodika/1900/pev/x.pdf")
    # тека без матеріалу, але з сайдкаром — «замовлено, не завантажено»
    touch("dahmo_230/spr-99/_source.json", b'{"frames": 7}')
    # кадри на шар глибше, у `pages/`
    touch("cdiak_224/spr-864/meta.json", b"{}")
    touch("cdiak_224/spr-864/pages/0001.jpg")
    return tmp_path


def _by_glob(base: Path, max_depth: int = 4) -> list[str]:
    """Перерахунок ТОЧНО так, як його робили споживачі до `walk`."""
    out: list[str] = []
    for depth in ("*", "*/*", "*/*/*", "*/*/*/*")[:max_depth]:
        for d in sorted(base.glob(depth)):
            if not d.is_dir():
                continue
            if d.relative_to(base).parts[0] in _SKIP:
                continue
            out.append(str(d.relative_to(base)).replace("\\", "/"))
    return out


def _by_walk(base: Path, max_depth: int = 4) -> list[str]:
    return [s.rel_root for s in walk_root(base, max_depth=max_depth,
                                          skip_slugs=_SKIP)]


def test_order_and_membership_match_glob(tree):
    """Головний приймач: той самий перелік у тому самому ПОРЯДКУ."""
    assert _by_walk(tree) == _by_glob(tree)


def test_depth_limit_matches(tree):
    """Обмеження глибини поводиться як менша кількість `glob`-патернів."""
    for depth in (1, 2, 3, 4):
        assert _by_walk(tree, depth) == _by_glob(tree, depth), f"глибина {depth}"


def test_case_insensitive_order_on_this_platform(tree):
    """`alpha` і `Beta` йдуть у тому ж порядку, що й у `sorted(Path)`."""
    walked = [r for r in _by_walk(tree, 1)]
    expected = [str(p.relative_to(tree)) for p in sorted(tree.glob("*"))
                if p.is_dir() and p.name not in _SKIP]
    assert walked == expected


def test_hidden_and_underscore_dirs_are_not_lost(tree):
    """Приховану теку видно, а всередину `_drafts` ми заходимо."""
    rels = _by_walk(tree)
    assert ".hidden" in rels
    assert "_drafts" in rels
    assert "_drafts/real_case" in rels, (
        "у теку з `_` на початку треба ЗАХОДИТИ — `glob` заходить, і там бувають справи"
    )


def test_skip_slug_prunes_whole_subtree(tree):
    rels = _by_walk(tree)
    assert not [r for r in rels if r.split("/")[0] == "periodika"]


def test_counts_match_direct_listing(tree):
    """Лічильники теки збігаються з прямим переліком файлів."""
    scans = {s.rel_root: s for s in walk_root(tree, skip_slugs=_SKIP)}

    beta = scans["Beta"]
    assert (beta.n_img, beta.n_pdf) == (1, 1)
    assert beta.pdf_names == ("скан.pdf",)

    spr99 = scans["dahmo_230/spr-99"]
    assert not spr99.has_material()
    assert spr99.sidecar == "_source.json"

    d864 = scans["cdiak_224/spr-864"]
    assert not d864.has_material() and d864.sidecar == "meta.json"
    assert "pages" in d864.dirs
    assert scans["cdiak_224/spr-864/pages"].n_img == 1


def test_sidecar_priority_is_source_json_over_meta_json(tmp_path):
    """Обидва сайдкари поруч — виграє `_source.json`, незалежно від порядку читання."""
    d = tmp_path / "case"
    d.mkdir()
    (d / "meta.json").write_bytes(b"{}")
    (d / "_source.json").write_bytes(b"{}")
    scan = next(iter(walk_root(tmp_path)))
    assert scan.sidecar == "_source.json"


def test_unreadable_dir_is_a_state_not_a_crash(tmp_path, monkeypatch):
    """Тека, яку не прочитати, позначається — обхід не падає."""
    (tmp_path / "case").mkdir()
    import nyshporka.cases.walk as W

    real = W.os.scandir

    def boom(p):
        if str(p).endswith("case"):
            raise PermissionError("нема доступу")
        return real(p)

    monkeypatch.setattr(W.os, "scandir", boom)
    scans = list(walk_root(tmp_path))
    assert len(scans) == 1 and scans[0].unreadable is True


def test_names_sha1_reacts_to_every_kind_of_change(tmp_path):
    """Дайджест імен ловить додавання, видалення, перейменування і зміну розміру.

    Це фундамент інкрементальності (етап 6): якщо він сліпий до якогось класу
    змін, перезбірка тихо пропустить теку.
    """
    d = tmp_path / "case"
    d.mkdir()
    (d / "0001.jpg").write_bytes(b"x")

    def h() -> str:
        return next(iter(walk_root(tmp_path))).names_sha1

    base = h()
    (d / "0002.jpg").write_bytes(b"x")
    added = h()
    assert added != base, "додавання файла не змінило дайджест"

    (d / "0002.jpg").unlink()
    assert h() == base, "після видалення дайджест мусить повернутись до вихідного"

    (d / "0001.jpg").rename(d / "0001b.jpg")
    assert h() != base, "перейменування не змінило дайджест"

    (d / "0001b.jpg").rename(d / "0001.jpg")
    (d / "0001.jpg").write_bytes(b"xxxxx")
    assert h() != base, "зміна розміру не змінила дайджест"
