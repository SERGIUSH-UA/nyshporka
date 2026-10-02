"""Старі ключі справ (до 0.22): заморожений будівник і карта переїзду.

До 0.22 опис входив у ключ лише там, де колізію вже хтось помітив: фонди зі
списку нижче і окремі справи з реєстру `data/cases/opys_keys.json`. Решта
справ мала ключ `REPO/фонд/справа`. Цим ключем записані сховище сторінок,
прив'язки прогонів, вердикти, мети прогонів — і нотатки, пам'ять агента,
чужі повідомлення, яких ніхто не перепише.

🔴 Будівник не правиться. Він відповідає на одне питання: «яким ключем ця
справа звалась до 0.22», і відповідь мусить бути тією, яку давав старий код,
а не кращою. Покращений старий ключ уже не знаходить записаного ним.

Старий рядок перекладається ЛИШЕ тут (`translate`, `current_key`): карта, яку
записав перенос обліку (`cases.rekey`), а до переносу — карта, порахована з
бібліотеки. Решта пакета старого ключа не розбирає.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: Фонди, де опис входив у ключ. Копія `library._OPYS_IN_KEY` станом на 0.21.5
#: (з ЦДІАК ф.127, внесеним 2026-10-01).
OPYS_IN_KEY: frozenset[tuple[str, str]] = frozenset({
    ("ANRM", "211"), ("DAHMO", "230"), ("DAVIO", "R-6129"), ("DAVO", "R-6129"),
    ("DAZHO", "1"), ("DAZHO", "118"), ("DAVOO", "382"), ("DAHMO", "196"),
    ("CDIAK", "127"),
})

#: Реєстр справ, що діставали ключ з описом поштучно (народжені в колізії).
REGISTRY = Path("data") / "cases" / "opys_keys.json"


def _norm(part: object) -> str:
    """Та сама форма, що й у старому реєстрі: «0213» і «213» — одна справа."""
    s = str(part or "").strip().casefold()
    return s.lstrip("0") or s


def registry_rows(root: Path) -> list[dict[str, Any]]:
    """Записи старого реєстру колізій як є; файла немає — порожньо."""
    p = root / REGISTRY
    if not p.is_file():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    return list((data or {}).get("cases") or [])


def registry_set(root: Path) -> frozenset[tuple[str, str, str, str]]:
    return frozenset((str(r.get("repo") or "").strip().upper(), _norm(r.get("fond")),
                      _norm(r.get("opys")), _norm(r.get("spr")))
                     for r in registry_rows(root))


def legacy_key(repo: str | None, fond: str | None, spr: str | None,
               opys: str | None, registry: frozenset[tuple[str, str, str, str]]
               ) -> str | None:
    """Ключ, яким справа звалась до 0.22 (`library._mk_key` 0.21.5)."""
    if not (repo and fond and spr):
        return None
    quad = (str(repo).strip().upper(), _norm(fond), _norm(opys), _norm(spr))
    with_opys = bool(opys) and not str(spr).startswith("@") and (
        (repo, str(fond)) in OPYS_IN_KEY or (bool(registry) and quad in registry))
    if with_opys:
        return f"{repo}/{fond}-{opys}/{spr}"
    return f"{repo}/{fond}/{spr}"


# ── карта переїзду: старий ключ → новий ──────────────────────────────────────
#: Карта, записана переносом (`nysh cases rekey --apply`). Лишається назавжди:
#: старі ключі живуть у нотатках, пам'яті агента, чужих повідомленнях, і кожен
#: з них мусить і далі вести до своєї справи.
MOVES = Path("data") / "cases" / "key_moves.json"

_cache: dict[str, Any] = {"stamp": None, "moves": {}}


def moves_from_entries(entries: list[dict[str, Any]],
                       registry: frozenset[tuple[str, str, str, str]]
                       ) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Карта зі списку записів бібліотеки + старі ключі, що вели до кількох справ.

    Старий ключ запису — `legacy_key` у записі (бібліотека, збудована до 0.22,
    тримає його як є) або порахований замороженим будівником. Новий — з полів.
    Кілька записів під одним старим ключем: як і до 0.22, ключ належить
    ПЕРШОМУ (`LibraryLookup` брав першого), решта перелічується.
    """
    from nyshporka.core import casekey

    out: dict[str, str] = {}
    shared: dict[str, list[str]] = {}
    for e in entries:
        new = casekey.make(e.get("repo"), e.get("fond"), e.get("opys"), e.get("spr"))
        old = e.get("legacy_key") or legacy_key(
            e.get("repo"), e.get("fond"), e.get("spr"), e.get("opys"), registry)
        if not (new and old) or old == new:
            continue
        if old in out:
            if out[old] != new:
                shared.setdefault(old, [out[old]]).append(new)
            continue
        out[old] = new
    return out, shared


def _stamp(root: Path) -> tuple[Any, ...]:
    from nyshporka.library import LIBRARY_PATH

    st: list[tuple[str, int | None, int | None]] = []
    for p in (root / MOVES, LIBRARY_PATH, root / REGISTRY):
        try:
            s = p.stat()
            st.append((str(p), s.st_mtime_ns, s.st_size))
        except OSError:
            st.append((str(p), None, None))
    return tuple(st)


def moves(root: Path | None = None) -> dict[str, str]:
    """Старий ключ → новий для цього простору.

    Записана карта (після переносу) — головна. До переносу карта рахується з
    бібліотеки: так старі рядки читаються ще до того, як облік переїхав.
    """
    if root is None:
        try:
            from nyshporka.core.workspace import workspace

            root = workspace().root
        except Exception:   # простору немає (сервер Супряги) — старих ключів теж
            return {}
    stamp = _stamp(root)
    if _cache["stamp"] == stamp:
        return dict(_cache["moves"])
    f = root / MOVES
    if f.is_file():
        got = dict((json.loads(f.read_text(encoding="utf-8")) or {}).get("moves") or {})
    else:
        # Той самий кешований індекс, що й у резолвера: бібліотеку не читаємо
        # вдруге (на просторі з тисячами прогонів це секунди на кожну команду).
        from nyshporka.library import library_lookup

        got, _ = moves_from_entries(list(library_lookup().entries), registry_set(root))
    _cache.update(stamp=stamp, moves=got)
    return dict(got)


def normalize_old(value: str) -> str | None:
    """Старий ключ у канонічних номерах: `DAHMO/315/08433` → `DAHMO/315/8433`.

    Форма та сама, що будував `legacy_key` (опис — хвостом фонду). `None` —
    рядок не є старим ключем.
    """
    from nyshporka.core import casekey

    parsed = casekey.parse_legacy(value)
    if not parsed:
        return None
    repo, fond, opys, spr = parsed
    return f"{repo}/{fond}-{opys}/{spr}" if opys else f"{repo}/{fond}/{spr}"


def translate(value: str, root: Path | None = None) -> str | None:
    """Старий ключ → новий за картою; `None` — карта цього ключа не знає.

    Рядок звіряється і як є, і зведений до канонічних номерів: `DAHMO/315/08433`
    та `DAHMO/315/8433` — той самий старий ключ.
    """

    s = str(value or "").strip()
    if not s:
        return None
    mv = moves(root)
    if s in mv:
        return mv[s]
    norm = normalize_old(s)
    return mv.get(norm) if norm else None


def reset() -> None:
    """Скинути кеш карти — тести, перенос."""
    _cache.update(stamp=None, moves={})


def current_key(value: str, *, repo: str | None = None, fond: str | None = None,
                opys: str | None = None, spr: str | None = None) -> str:
    """Будь-який записаний ключ → ключ нової форми; не розібрався — як є.

    Порядок: ключ уже нової форми → карта переїзду → поля запису (`repo`,
    `fond`, `opys`, `spr`, якщо файл їх несе) або частини старого ключа з
    описом за замовчуванням фонду. Поля сильніші за розбір рядка: їх писали
    разом із ключем, і вони не губили опису.
    """
    from nyshporka.core import casekey

    s = str(value or "").strip()
    ck = casekey.parse(s)
    if not s or (ck is not None and (ck.opys_known or ck.bundle)):
        return s
    if ck is not None:
        # Ключ з невідомим описом, якому перенос уже знайшов опис.
        return moves().get(s, s)
    moved = translate(s)
    if moved:
        return moved
    old = casekey.parse_legacy(s)
    r, f, o, sp = old if old else (None, None, None, None)
    r, f, sp = repo or r, fond or f, spr or sp
    o = opys or o
    if not (r and r != "?" and f and sp):
        return s
    if not o and not casekey.is_bundle(sp):
        from nyshporka.library import default_opys

        o = default_opys(r, casekey.norm_fond(f))
    return casekey.make(r, f, o, sp) or s


# ── читання сховищ, ключованих справою ───────────────────────────────────────
def rekeyed(d: dict[str, Any]) -> dict[str, Any]:
    """Словник «ключ справи → запис» з ключами нової форми.

    До переносу обліку сховища (вердикти, журнал пошуку, картки) тримають
    старі ключі, а читачі питають новими. Двоє старих під одним новим — перший
    лишається (перенос зливає їх, а читання до переносу показує першого).
    """
    out: dict[str, Any] = {}
    for k, v in d.items():
        nk = k if str(k).startswith("_") else current_key(str(k))
        out.setdefault(nk, v)
    return out


def get(d: dict[str, Any], key: str) -> Any:
    """Запис справи зі словника за будь-якою формою ключа; немає — `None`."""
    from nyshporka.core import casekey

    if not d or not key:
        return None
    if key in d:
        return d[key]
    want = current_key(key)
    if want in d:
        return d[want]
    for k, v in d.items():
        if casekey.is_legacy(k) and current_key(k) == want:
            return v
    return None
