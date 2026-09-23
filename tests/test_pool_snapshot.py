"""🤝 Зріз Супряги: третій шар поруч з описом фонду й бібліотекою.

Тут стережуть три речі, і кожна вже ламалась або мало не зламалась:

1. **«Не знаємо» ≠ «немає».** Доки зрізу не знято, правдива відповідь одна —
   «не питали». Сказати «в пулі немає» означає послати людину платити за прогін
   тексту, який лежить готовий.
2. **Літера індексу справи.** Реєстр опису тримає її так, як надруковано в
   описі (`84а`, кирилицею), пул — у каноні сховища сторінок (`84a`, латинкою).
   Перша жива проба показала порожню колонку саме на цих справах: текст у пулі
   був, мітки не було.
3. **Показ не ходить у мережу.** Це обіцянка PRIVACY, і довести її можна лише
   тим, що читач фізично відокремлений від дроту (`share/pool.py` проти
   `share/catalog.py`).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from nyshporka.core import workspace as W
from nyshporka.fonds import registry as R
from nyshporka.share import pool


@pytest.fixture
def prostir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Порожній простір: жодного зрізу, жодного реєстру."""
    monkeypatch.setenv("NYSHPORKA_WORKSPACE", str(tmp_path))
    W.use(tmp_path)
    pool.invalidate()
    return tmp_path


def _zriz(rows: list[dict[str, Any]], *, taken_at: str = "2026-09-23T10:00:00+00:00") -> None:
    """Покласти зріз руками — щоб не ходити в мережу заради фікстури."""
    pool.pool_dir().mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(pool.snapshot_path())
    try:
        for ddl in pool._DDL:
            con.execute(ddl)
        for r in rows:
            con.execute("INSERT INTO pool VALUES (?,?,?,?,?,?,?,?,?,?)", (
                r["key"], r["repo"], r["fond"], r["opys"], r["spr"],
                r.get("n", 1), r.get("pages", 0), 1 if r.get("geom") else 0,
                json.dumps(r.get("publishers", []), ensure_ascii=False),
                r.get("updated", "")))
        for k, v in (("schema", str(pool.SCHEMA)), ("base", "https://x/v1"),
                     ("taken_at", taken_at), ("of", str(len(rows))),
                     ("scope", "все"), ("via", "keys")):
            con.execute("INSERT INTO meta VALUES (?,?)", (k, v))
        con.commit()
    finally:
        con.close()
    pool.invalidate()


# ── 1. «не знаємо» проти «немає» ──────────────────────────────────────────────

def test_bez_zrizu_ne_te_same_shcho_porozhnii_zriz(prostir: Path) -> None:
    """🔴 `None` = зрізу не брали; `{}` = зріз є, у фонді порожньо.

    Одне значення на обидва випадки — і колонка каже «немає» там, де ми просто
    не дивились. Це та сама межа, що `layers.summary()` тримає для реєстру
    справ: `None` ≠ `0`.
    """
    assert pool.by_fond("DAHMO", "315") is None
    assert pool.meta() is None

    _zriz([{"key": "DAVIO/904/24/105", "repo": "DAVIO", "fond": "904",
            "opys": "24", "spr": "105"}])

    assert pool.by_fond("DAHMO", "315") == {}, "зріз є — фонд порожній, а не невідомий"
    assert pool.by_fond("DAVIO", "904") != {}
    assert (pool.meta() or {}).get("of") == 1


def test_row_status_bez_argumenta_kazhe_ne_znaiemo(prostir: Path) -> None:
    """Хто забув передати `pool=`, дістає видиме «не знаємо», а не тихе «немає».

    🔴 Саме заради цього пул увійшов аргументом `row_status`, а не окремою
    функцією поруч: забута функція лишила б поле відсутнім, і рендерер намалював
    би порожньо — тобто збрехав би.
    """
    row = {"opys": "1", "spr_int": "6940", "spr_letter": "", "spr": "6940"}

    st = R.row_status(row, {}, {})

    assert st["pool"] is None
    assert st["pool_n"] is None
    assert st["pool_mine"] is None


# ── 2. літера індексу ─────────────────────────────────────────────────────────

def test_litera_reiestru_kyryltseiu_znakhodyt_pul_latynkoiu(prostir: Path) -> None:
    """🪤 Реєстр має `84а`, пул — `84a`. Без перекладу колонка мовчить.

    Це не теоретичний випадок: на першій живій пробі ДАХмО 315-1-84а мала текст
    у пулі й порожню клітинку в таблиці.
    """
    _zriz([{"key": "DAHMO/315/1/84a", "repo": "DAHMO", "fond": "315",
            "opys": "1", "spr": "84a", "n": 2, "pages": 222,
            "publishers": ["sergiush"]}])
    pm = pool.by_fond("DAHMO", "315")
    row = {"opys": "1", "spr_int": "84", "spr_letter": "а", "spr": "84а"}

    st = R.row_status(row, {}, {}, None, pool=pm)

    assert st["pool"] == "text", "кирилична літера опису не знайшла пулу"
    assert st["pool_n"] == 2


def test_quad_key_zbihaietsia_z_resolve_case(prostir: Path) -> None:
    """Ключ зрізу будується тим самим каноном, що й ключ сервера.

    🔴 `app/shifra.py` на сервері нормалізує через `pagestore.resolve_case`.
    Якщо `quad_key` розійдеться з ним, ключі не зійдуться — і колонка буде
    порожня при повному пулі, без жодної помилки.
    """
    from nyshporka.pagestore import resolve_case

    for text in ("ДАХмО 315-1-84а", "ДАХмО 315-1-84a", "ДАХмО 315-1-06940"):
        ref = resolve_case(text)
        assert pool.quad_key(ref.repo, ref.fond, ref.opys or "", ref.spr) == \
            f"{ref.repo}/{ref.fond}/{ref.opys or ''}/{ref.spr}"


# ── 3. показ без мережі ───────────────────────────────────────────────────────

def test_pokaz_ne_khodyt_u_merezhu(prostir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Приймач обіцянки PRIVACY.

    Глушиться ТРАНСПОРТ, а не конкретний клас: підміна одного `Fetcher`
    пропустила б прямий `httpx` чи сокет, і тест лишався б зеленим, нічого не
    доводячи.
    """
    import socket

    import nyshporka.sources.http as H

    def _zaboronene(*_: Any, **__: Any) -> None:
        raise AssertionError("показ колонки пішов у мережу")

    monkeypatch.setattr(H.Fetcher, "get", _zaboronene)
    monkeypatch.setattr(H.Fetcher, "download", _zaboronene)
    monkeypatch.setattr(socket.socket, "connect", _zaboronene)

    # заборона мусить довести, що вона жива, перш ніж нею користуватись
    with pytest.raises(AssertionError):
        socket.socket().connect(("127.0.0.1", 9))

    _zriz([{"key": "DAHMO/315/1/6940", "repo": "DAHMO", "fond": "315",
            "opys": "1", "spr": "6940", "n": 1, "pages": 281}])

    pm = pool.by_fond("DAHMO", "315")
    row = {"opys": "1", "spr_int": "6940", "spr_letter": "", "spr": "6940"}

    assert R.row_status(row, {}, {}, None, pool=pm)["pool"] == "text"
    assert pool.by_key("DAHMO/315/1/6940") is not None
    assert pool.meta() is not None
    assert pool.age_days() is not None


# ── 4. дрібніше, але з причини ────────────────────────────────────────────────

def test_mii_vnesok_nevidomyi_bez_psevdonima(prostir: Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    """Порожній `handle` → `mine is None`, а не `False`.

    Людина без псевдоніма не має права бачити «не ваш» там, де відповіді немає.
    """
    monkeypatch.setattr(pool, "_handle", lambda: "")
    _zriz([{"key": "DAHMO/315/1/6940", "repo": "DAHMO", "fond": "315",
            "opys": "1", "spr": "6940", "publishers": ["khtos"]}])

    cell = pool.by_key("DAHMO/315/1/6940")

    assert cell is not None and cell.mine is None


def test_vik_zrizu_vidomyi(prostir: Path) -> None:
    """Вік показується скрізь, де показується значення: «є/немає» — на дату."""
    _zriz([], taken_at="2026-08-01T00:00:00+00:00")

    age = pool.age_days()

    assert age is not None and age > pool.STARYI_DNIV
    assert pool.stale() is True


def test_state_of_rozriznyaie_heometriiu() -> None:
    """Текст і текст із рамками — різні відповіді: від них залежить, чи можна кроп."""
    assert pool.state_of(None) == "none"
    assert pool.state_of(pool.PoolCell(n=1)) == "text"
    assert pool.state_of(pool.PoolCell(n=1, geom=True)) == "text+geom"
