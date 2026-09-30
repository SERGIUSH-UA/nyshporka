"""🔗 Ланцюг справи: скани → паспорт → реєстрація → бібліотека → прогін.

Кожна ланка має свій файл і свою команду, і жодна не каже про сусідню.
Завантажувач кладе кадри й `meta.json`; бібліотека бере теку, лише якщо з
її імені чи паспорта збирається ключ справи; прогін прив'язується до справи
за тим самим ключем. Тека, на якій ключ не зібрався, випадає з усього одразу
— мовчки: її немає в бібліотеці, прогін по ній «нічий», віддати нічого.

🔴 Привід — звіт стороннього користувача 29.09.2026: двадцять завантажених
справ, у кожній `meta.json` завантажувача, жодної реєстрації. Він дивився на
`meta.json` і вважав справу описаною; справжній паспорт — `_source.json`, і
пише його лише `nysh case … --shifra`. Ніщо цього не сказало.

Тут — одна логіка на три обличчя: `nysh cases chain`, перевірка в `nysh
doctor` і порада одразу після завантаження.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from functools import partial
from pathlib import Path
from typing import Any

#: Ланки, на яких ланцюг ОБІРВАНО: далі справа не йде, доки людина не втрутиться.
OUTSIDE_ROOTS = "outside_roots"      # тека поза коренями справ — її ніхто не бачить
LOADER_ONLY = "loader_only"          # є паспорт завантаження, шифри немає
NO_PASSPORT = "no_passport"          # кадри є, шифри взяти нізвідки
NOT_IN_LIBRARY = "not_in_library"    # шифра є, каталог справ зібрано раніше
ORPHAN_RUN = "orphan_run"            # прогін без справи

#: Стани, що обривом не є: справа в обліку, питання лише в читанні.
NO_RUN = "no_run"
PARTIAL_RUN = "partial_run"
OK = "ok"

BREAKS = (OUTSIDE_ROOTS, LOADER_ONLY, NO_PASSPORT, NOT_IN_LIBRARY, ORPHAN_RUN)

#: Назва ланки для людини.
NAZVY = {
    OUTSIDE_ROOTS: "тека поза коренями справ",
    LOADER_ONLY: "є паспорт завантаження, справу не зареєстровано",
    NO_PASSPORT: "кадри без шифри справи",
    NOT_IN_LIBRARY: "шифра є, у каталозі справ теки немає",
    ORPHAN_RUN: "прогін без справи",
    NO_RUN: "у каталозі, не читано",
    PARTIAL_RUN: "у каталозі, прочитано частково",
    OK: "у каталозі, прочитано",
}

#: Поля, які в `meta.json` лишає завантажувач (`acquire.record_fetch`).
_LOADER_FIELDS = ("fetched_by", "fetched_from", "fetch_state", "frames_got")

#: Шифра, якої ще немає, — місце, куди її вписати.
SHIFRA_PLACEHOLDER = "<архів фонд-опис-справа>"


@dataclass(frozen=True)
class Lanka:
    """Одна тека (або прогін) і ланка, на якій вона стоїть."""

    path: str
    link: str
    frames: int = 0
    sidecar: str = ""
    key: str = ""
    why: str = ""
    fix: str = ""

    @property
    def broken(self) -> bool:
        return self.link in BREAKS

    def as_json(self) -> dict[str, Any]:
        return {**asdict(self), "broken": self.broken}


# ── одна тека ─────────────────────────────────────────────────────────────────

def sidecar_of(case_dir: Path) -> tuple[str, dict[str, Any]]:
    """Найсильніший сайдкар теки: `(ім'я, вміст)` або `("", {})`.

    Кадри в `pages/` (так кладе ARCHIUM) — сайдкар лежить на рівень вище.
    """
    from nyshporka.cases.walk import SIDECAR_NAMES

    d = Path(case_dir)
    dirs = [d, d.parent] if d.name == "pages" else [d]
    for name in SIDECAR_NAMES:
        for x in dirs:
            f = x / name
            if not f.is_file():
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
            return name, data if isinstance(data, dict) else {}
    return "", {}


def claimed_shifra(meta: dict[str, Any]) -> str:
    """Шифра, яку назвала сторінка джерела, — підказка, не факт.

    Завантажувач кладе її в `shifra_claimed` навмисно не під іменем `shifra`:
    оком її ніхто не звіряв, а помилка на один номер приписує теці чужу справу.
    """
    from nyshporka import library as L

    got = meta.get("shifra_claimed")
    if not isinstance(got, dict):
        return ""
    repo = str(got.get("repo") or got.get("archive") or "").strip()
    fond = str(got.get("fond") or "").strip()
    opys = str(L._sidecar_opys(got) or "").strip()
    spr = str(got.get("spr") or got.get("sprava") or "").strip()
    if not (fond and spr):
        return ""
    return f"{repo} {'-'.join(x for x in (fond, opys, spr) if x)}".strip()


def _is_case_download(meta: dict[str, Any]) -> bool:
    """Чи `meta.json` — слід завантаження СПРАВИ, а не книжки чи збірки."""
    return any(k in meta for k in _LOADER_FIELDS) and "book" not in meta


def _rel(case_dir: Path) -> str:
    """Шлях, яким теку знає бібліотека: відносний у просторі, інакше абсолютний."""
    from nyshporka import library as L

    p = Path(os.path.abspath(case_dir))
    try:
        return p.relative_to(os.path.abspath(L.ROOT)).as_posix()
    except ValueError:
        return p.as_posix()


def _register_cmd(path: str, meta: dict[str, Any]) -> tuple[str, str]:
    """Команда реєстрації й примітка до неї."""
    hint = claimed_shifra(meta)
    cmd = f'nysh case "{path}" --shifra "{hint or SHIFRA_PLACEHOLDER}"'
    note = (f" (шифра «{hint}» — зі сторінки джерела, оком не звірена)" if hint else "")
    return cmd, note


def judge(case_dir: Path, *, frames: int = 0,
          runs: dict[str, list[dict[str, Any]]] | None = None) -> Lanka:
    """На якій ланці стоїть ця тека.

    `runs` — мапа «тека → прогони» (`htr_store.runs_by_case_dir`); `None` —
    прогони не питались, і стан читання не визначається: тека в каталозі
    лишається `ok` лише в сенсі «ланцюг до каталогу цілий».
    """
    from nyshporka import library as L
    from nyshporka.cases.collect import _COVERAGE_OK
    from nyshporka.cases.register import case_path, reachable

    abs_dir = case_path(case_dir)
    rel = _rel(abs_dir)
    name, meta = sidecar_of(abs_dir)
    mk = partial(Lanka, path=rel, frames=frames, sidecar=name)
    cmd, note = _register_cmd(rel, meta)

    if not reachable(abs_dir):
        return mk(link=OUTSIDE_ROOTS,
                  why="тека лежить поза коренями справ — каталог її не обходить",
                  fix=f"{cmd} --adopt{note}")

    parsed = L.parse_case_path(rel)
    if not parsed:
        # 🔴 Саме слід завантажувача, а не будь-який `meta.json`: так само
        # називається опис книжки чи збірки, яку справою ніхто не вважав. Теку,
        # яку людина щойно ЗАВАНТАЖИЛА як справу й не зареєструвала, від них
        # відрізняють поля `record_fetch`. Книжка з бібліотеки (`book`) —
        # теж завантаження, але справою її ніхто не називав.
        if name == "meta.json" and _is_case_download(meta):
            return mk(link=LOADER_ONLY,
                      why=("у теці лише `meta.json` завантажувача — це запис про "
                           "завантаження, а не паспорт справи (`_source.json`)"),
                      fix=f"{cmd}{note}")
        why = (f"у `{name}` немає шифри" if name
               else "паспорта немає, а з імені теки шифру не зібрати")
        return mk(link=NO_PASSPORT, why=why, fix=f"{cmd}{note}")

    keys = L.candidate_keys(parsed)
    lk = L.library_lookup() if L.LIBRARY_PATH.exists() else None
    found = lk is not None and (rel in lk.by_path or any(k in lk.by_key for k in keys))
    key = next((k for k in keys if lk is not None and k in lk.by_key), keys[0] if keys else "")
    if not found:
        return mk(link=NOT_IN_LIBRARY, key=key,
                  why="ключ справи збирається, але каталог справ зібрано до появи теки",
                  fix="nysh cases build --rescan")
    if runs is None:
        return mk(link=OK, key=key)
    # ARCHIUM кладе кадри в `pages/`: прогін знає теку з нею, каталог — без.
    moi = (runs.get(str(abs_dir)) or []) + (runs.get(str(abs_dir / "pages")) or [])
    if not moi:
        return mk(link=NO_RUN, key=key, fix=f'nysh read "{rel}"')
    pages = max(int(r.get("pages_done") or 0) for r in moi)
    if frames and pages / frames < _COVERAGE_OK:
        return mk(link=PARTIAL_RUN, key=key,
                  why=f"прочитано {pages} із {frames}", fix=f'nysh read "{rel}"')
    return mk(link=OK, key=key)


# ── увесь простір ─────────────────────────────────────────────────────────────

def _orphans() -> list[Lanka]:
    """Прогони без справи — з реєстру, якщо він зібраний."""
    from nyshporka.cases import db

    try:
        rows = db.orphan_runs()
    except (FileNotFoundError, OSError):
        return []
    out = []
    for r in rows:
        if (r.get("resolved_by") or "") == "override":
            continue                        # свідомо нічий — рішення людини
        out.append(Lanka(
            path=str(r.get("run") or ""), link=ORPHAN_RUN,
            frames=int(r.get("pages") or 0),
            why=f"прогін по теці {r.get('case_dir') or '—'} не зведено до справи",
            fix=f'nysh cases bind "{r.get("run")}" <ключ справи>'))
    return out


def _forget_caches() -> None:
    """Паспорти могли змінитись із минулого виклику в тому самому процесі."""
    from nyshporka import library as L

    clear = getattr(L._sidecar_case, "cache_clear", None)
    if clear is not None:
        clear()


def quick() -> list[Lanka] | None:
    """Обриви без обходу диска. `None` — реєстру справ ще немає.

    Дивиться лише на те, що реєстр уже знає як «матеріал без справи»
    (`kind=unfiled`), і на нічиї прогони. Нової теки, покладеної після
    останньої збірки реєстру, тут не видно — її бачить `walk()`.
    """
    from nyshporka import library as L
    from nyshporka.cases import db

    try:
        rows = db.query_rows(kind="unfiled")
    except (FileNotFoundError, OSError):
        return None
    _forget_caches()
    out: list[Lanka] = []
    for r in rows:
        path = str(r.get("path") or "")
        if not path or not (L.ROOT / path).is_dir():
            continue
        got = judge(L.ROOT / path, frames=int(r.get("frames") or 0))
        if got.broken:
            out.append(got)
    return out + _orphans()


def walk() -> list[Lanka]:
    """Усі теки з матеріалом у коренях справ — і ланка кожної.

    🔴 Обходить диск (ті самі теки, які обходить збірка каталогу), тому
    кличеться лише з волі людини. Зате бачить те, чого не бачить `quick()`:
    теку, покладену після збірки реєстру, і теки в додаткових коренях.
    """
    from nyshporka import htr_store
    from nyshporka import library as L

    _forget_caches()
    try:
        runs = htr_store.runs_by_case_dir()
    except Exception:
        runs = {}
    out: list[Lanka] = []
    # Тека, яку вже пораховано: її підтеки без власної шифри (`pages/`,
    # вирізки, робочі копії) — не окремі справи.
    vzhe: list[str] = []
    for path, imgs, pdfs in L._scan_disk_cases(limit=10**6):
        abs_dir = Path(path) if Path(path).is_absolute() else L.ROOT / path
        rel = _rel(abs_dir)
        pid = any(rel.startswith(p + "/") for p in vzhe)
        got = judge(abs_dir, frames=imgs or pdfs, runs=runs)
        if pid and got.link in (LOADER_ONLY, NO_PASSPORT):
            continue
        vzhe.append(rel)
        out.append(got)
    return out + _orphans()


def summary(rows: list[Lanka]) -> dict[str, int]:
    """Скільки на кожній ланці — у порядку ланцюга."""
    out = {k: 0 for k in (*BREAKS, NO_RUN, PARTIAL_RUN, OK)}
    for r in rows:
        out[r.link] = out.get(r.link, 0) + 1
    return out


def after_fetch(dest: Path) -> Lanka | None:
    """Що робити з текою одразу після завантаження. `None` — ланцюг цілий.

    Каталог тут не питається: він щойно не міг знати про цю теку. Питання
    одне — чи збереться з неї ключ справи, коли каталог перезбиратимуть.
    """
    _forget_caches()
    if "book" in sidecar_of(Path(dest))[1]:
        return None                 # книжка з бібліотеки — не справа
    got = judge(dest)
    return got if got.link in (OUTSIDE_ROOTS, LOADER_ONLY, NO_PASSPORT) else None
