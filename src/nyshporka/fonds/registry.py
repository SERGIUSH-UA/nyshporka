"""Читання реєстру опису фонду: нормалізація схем, фільтри, покриття, стан диска.

🔴 **Один фільтр на два входи.** Ця логіка була приватною всередині
`nyshporka.cases.cli` (замикання `keep()` у тілі команди), тож консоль не могла її
взяти. Копія в роутері зробила б `nysh cases fond --todo` і вкладку «🏛 Фонди»
двома реалізаціями одного питання — і перше ж розходження дало б два різні числа
«скільки качати», жодне з яких не видно як помилку.

🔴 **`None` ≠ `""`.** Фонди лежать у ДВОХ схемах:

    f230_opys_merged.tsv  25 колонок  merged_v2 (з `commons_title`, `surnames`)
    f481_opys_merged.tsv  23 колонки  merged_v2 без них
    f315_opys_merged.tsv   8 колонок  стара схема `dahmo_315_opys_merge.py`

Стара схема не знає ні `commons_url`, ні `on_disk`, ні `truncated_mirror`, ні
`num_src`. `None` означає «схема цього фонду такого поля не має», `""` — «поле є,
значення порожнє». Якщо їх злити, ф.315 виглядатиме як фонд, де немає жодного
обрізаного дзеркала, — а це неправда за замовчуванням, і мовчазна.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from nyshporka.core.workspace import workspace

REPO_SLUG = {"DAHMO": "dahmo", "CDIAK": "cdiak", "DAVO": "davo", "DAVIO": "davio",
             "DAOO": "daoo", "ANRM": "anrm", "DAZHO": "dazho"}
REPO_LABEL = {"DAHMO": "ДАХмО", "CDIAK": "ЦДІАК", "DAVO": "ДАВО", "DAVIO": "ДАВіО",
              "DAOO": "ДАОО", "ANRM": "ANRM", "DAZHO": "ДАЖО"}
_SLUG_REPO = {v: k for k, v in REPO_SLUG.items()}

#: канонічний набір полів нормалізованого рядка
FIELDS = ("opys", "spr_int", "spr_letter", "spr", "shifra", "title", "title_src",
          "title_alt", "commons_title", "year_from", "year_to", "years_src",
          "folios", "folios_src", "dv_no", "commons_url", "commons_size",
          "commons_pages", "mirror_url", "mirror_size", "truncated_mirror",
          "on_disk", "src_page", "page_quality", "num_src", "surnames",
          # 🎞 FamilySearch: окремий канал доступу до справи. `fs_dgs` — те, за
          # чим плівку відкривають; для фондів без оцифровки на Commons це
          # єдиний спосіб побачити документ, не замовляючи його в архіві.
          # 👁 прочитане оком з обкладинки: село книги і діапазон абетки збірного тому
          "cover_place", "cover_letters", "cover_note",
          "fs_dgs", "fs_film", "fs_url", "fs_record_type", "fs_place", "fs_frames",
          "sources")

#: поля, яких стара схема не має → `None`
_LEGACY_UNKNOWN = ("title_alt", "commons_title", "years_src", "folios", "folios_src",
                   "dv_no", "commons_url", "commons_size", "commons_pages",
                   "mirror_url", "mirror_size", "truncated_mirror", "on_disk",
                   "src_page", "page_quality", "num_src", "surnames",
                   "fs_dgs", "fs_url", "fs_record_type", "fs_place", "fs_frames",
                   "cover_place", "cover_letters", "cover_note")

_SPR_RE = re.compile(r"^(\d+)\s*([а-яіїєґa-z]?)$", re.IGNORECASE)
_KEY_RE = re.compile(r"^([A-Za-zА-Яа-яІЇЄҐіїєґ]+)[/\s-]+(\d+)[/\s-]+(?:(\d+)[/\s-]+)?"
                     r"(\d+)\s*([а-яіїєґa-z]?)$")
_YEAR_RE = re.compile(r"^(\d{4})(?:\s*[-–]\s*(\d{4}))?$")

#: memo: fond_id → (stamp, rows). stamp = (path, mtime_ns, size) — перезбірка реєстру
#: змінює mtime, тож кеш протухає сам і його не треба скидати руками.
_CACHE: dict[str, tuple[tuple[Any, ...], list[dict[str, Any]]]] = {}


# ── дискавері ─────────────────────────────────────────────────────────────────

def _stamp(p: Path) -> tuple[Any, ...]:
    st = p.stat()
    return (str(p), st.st_mtime_ns, st.st_size)


def fond_path(fond_id: str) -> Path:
    """`dahmo_230` → `data/raw/dahmo_230/f230_opys_merged.tsv`."""
    fond = fond_id.rsplit("_", 1)[-1]
    return workspace().raw / fond_id / f"f{fond}_opys_merged.tsv"


def registry_dir(fond_id: str) -> Path:
    return workspace().raw / fond_id / "registry"


def discover_fonds() -> list[dict[str, Any]]:
    """Усі реєстри описів на диску. Без хардкоду переліку фондів."""
    out: list[dict[str, Any]] = []
    raw = workspace().raw
    if not raw.exists():
        return out
    for p in sorted(raw.glob("*/f*_opys_merged.tsv")):
        fond_id = p.parent.name
        m = re.match(r"^f(\d+)_opys_merged\.tsv$", p.name)
        if not m:
            continue
        fond = m.group(1)
        slug_repo = fond_id.rsplit("_", 1)[0]
        repo = _SLUG_REPO.get(slug_repo, slug_repo.upper())
        st = p.stat()
        out.append({
            "id": fond_id, "repo": repo,
            "repo_label": REPO_LABEL.get(repo, repo), "fond": fond,
            "label": f"{REPO_LABEL.get(repo, repo)} ф.{fond}",
            "path": str(p), "mtime": st.st_mtime,
            "has_coverage": (registry_dir(fond_id) / "coverage.json").exists(),
            "has_conflicts": (registry_dir(fond_id) / "conflicts.tsv").exists(),
            "has_alfavitka": (registry_dir(fond_id) / "alfavitka.tsv").exists(),
        })
    return out


# ── читання й нормалізація ────────────────────────────────────────────────────

def _norm_legacy(r: dict[str, Any]) -> dict[str, Any]:
    """Стара схема ф.315 → канонічна форма.

    `has_commons` (0/1) НЕ стає `commons_url`: прапорець каже «скан десь є», а
    URL-а в цій схемі немає, тобто качати нічим. Плутати їх означало б показати
    кнопку ⬇, яка нічого не може зробити.
    """
    out: dict[str, Any] = {k: None for k in _LEGACY_UNKNOWN}
    spr_raw = (r.get("spr") or "").strip()
    m = _SPR_RE.match(spr_raw)
    out["opys"] = (r.get("opys") or "").strip()
    out["spr_int"] = m.group(1) if m else spr_raw
    out["spr_letter"] = (m.group(2).lower() if m else "")
    out["title"] = (r.get("title") or "").strip()
    out["title_src"] = (r.get("source") or "").strip()
    out["year_from"] = (r.get("year_from") or "").strip()
    out["year_to"] = (r.get("year_to") or "").strip()
    out["sources"] = (r.get("source") or "").strip()
    out["commons_flag"] = str(r.get("has_commons") or "").strip() in {"1", "true", "yes"}
    out["fs_film"] = (r.get("fs_film") or "").strip()
    return out


def _norm_merged(r: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in FIELDS:
        if k in ("spr", "shifra"):
            continue
        out[k] = r.get(k) if k in r else None
        if isinstance(out[k], str):
            out[k] = out[k].strip()
    out["commons_flag"] = bool(out.get("commons_url"))
    # ⚠ Тут стояло `out["fs_film"] = ""` — залишок часів, коли merged-схема поля
    # не мала. Після міграції майстер-індексу FS у реєстр воно затирало живі
    # дані: 12 794 справи з плівкою читались як «плівки немає».
    out["fs_film"] = (out.get("fs_film") or "")
    return out


def load_rows(fond_id: str) -> list[dict[str, Any]]:
    """Нормалізовані рядки реєстру опису; memo за (path, mtime, size)."""
    p = fond_path(fond_id)
    if not p.exists():
        return []
    stamp = _stamp(p)
    hit = _CACHE.get(fond_id)
    if hit and hit[0] == stamp:
        return hit[1]

    with p.open(encoding="utf-8", newline="") as fh:
        rd = csv.DictReader(fh, delimiter="\t")
        cols = set(rd.fieldnames or [])
        legacy = "spr_int" not in cols
        raw = list(rd)

    fond = fond_id.rsplit("_", 1)[-1]
    rows: list[dict[str, Any]] = []
    for r in raw:
        n = _norm_legacy(r) if legacy else _norm_merged(r)
        n["spr"] = f"{n.get('spr_int') or ''}{n.get('spr_letter') or ''}"
        n["shifra"] = f"{fond}-{n.get('opys') or ''}-{n['spr']}"
        n["schema"] = "legacy" if legacy else "merged_v2"
        rows.append(n)
    _CACHE[fond_id] = (stamp, rows)
    return rows


def invalidate(fond_id: str | None = None) -> None:
    if fond_id:
        _CACHE.pop(fond_id, None)
    else:
        _CACHE.clear()


def schema_of(fond_id: str) -> str:
    rows = load_rows(fond_id)
    return rows[0]["schema"] if rows else "unknown"


# ── супутні файли ─────────────────────────────────────────────────────────────

def load_coverage(fond_id: str) -> dict[str, Any] | None:
    p = registry_dir(fond_id) / "coverage.json"
    if not p.exists():
        return None
    try:
        return dict(json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        return None


def load_conflicts(fond_id: str) -> list[dict[str, Any]] | None:
    p = registry_dir(fond_id) / "conflicts.tsv"
    if not p.exists():
        return None
    with p.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def load_alfavitka(fond_id: str) -> list[dict[str, Any]] | None:
    p = registry_dir(fond_id) / "alfavitka.tsv"
    if not p.exists():
        return None
    with p.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def conflicts_index(fond_id: str) -> dict[tuple[str, str], int]:
    """(опис, справа) → скільки рядків розбіжностей."""
    rows = load_conflicts(fond_id)
    if rows is None:
        return {}
    idx: dict[tuple[str, str], int] = {}
    for r in rows:
        k = ((r.get("opys") or "").strip(), (r.get("spr") or "").strip())
        idx[k] = idx.get(k, 0) + 1
    return idx


# ── живий стан диска ──────────────────────────────────────────────────────────

def live_on_disk(repo: str, fond: str) -> dict[tuple[str, str, str], str]:
    """(опис, номер, літера) → шлях; ЖИВИЙ стан із бібліотеки.

    🔴 Колонка `on_disk` у TSV — не з диска: `fond_registry_merge.py` бере її з
    `case_library.json` на момент останнього merge. Одразу після завантаження
    справи вона бреше, доки merge не перезапустять. Тому UI показує обидва
    значення й називає розбіжність, замість підмінити одне іншим мовчки.

    Ключ несе ОПИС і ЛІТЕРУ: номер справи неунікальний між описами, а «24» і
    «24а» — різні книги (без цього 11 справ на диску показувались як 16).
    """
    try:
        from nyshporka.library import load_library
    except Exception:
        return {}
    try:
        data = load_library()
    except Exception:
        return {}
    cases = data.get("cases", []) if isinstance(data, dict) else data
    out: dict[tuple[str, str, str], str] = {}
    for c in cases:
        if str(c.get("fond") or "") != str(fond):
            continue
        if (str(c.get("repo") or "").upper() or repo) != repo.upper():
            continue
        m = _SPR_RE.match(str(c.get("spr") or ""))
        if not m:
            continue
        opys = str(c.get("opys") or "1")
        out[(opys, m.group(1), m.group(2).lower())] = c.get("path") or ""
    return out


# ── похідні для UI ────────────────────────────────────────────────────────────

def row_status(row: dict[str, Any],
               live: dict[tuple[str, str, str], str],
               conflicts: dict[tuple[str, str], int]) -> dict[str, Any]:
    """`disk_state`, `flags`, `on_disk_live`, `disk_mismatch`, `conflicts`."""
    key = (row.get("opys") or "", row.get("spr_int") or "",
           row.get("spr_letter") or "")
    on_live = live.get(key, "")
    on_tsv = row.get("on_disk")
    flags: list[str] = []
    if row.get("truncated_mirror"):
        flags.append("truncated")
    if row.get("num_src") == "interp":
        flags.append("interp")
    if row.get("page_quality") == "lo":
        flags.append("lo")
    if row.get("title_alt"):
        flags.append("title_conflict")
    if not (row.get("title") or "").strip():
        flags.append("no_title")
    if row.get("spr_letter"):
        flags.append("letter")

    if on_live:
        state = "disk"
    elif row.get("commons_url"):
        state = "todo"
    elif row.get("mirror_url"):
        state = "mirror_only"
    else:
        state = "order"

    return {
        "on_disk_live": on_live,
        # розходження лише там, де схема взагалі знає про `on_disk`
        "disk_mismatch": (on_tsv is not None and bool(on_tsv) != bool(on_live)),
        "disk_state": state,
        "flags": flags,
        "conflicts": conflicts.get((row.get("opys") or "", row.get("spr") or ""), 0),
    }


# ── фільтр (один на CLI і на UI) ──────────────────────────────────────────────

def _year_bounds(year: str | None) -> tuple[int | None, int | None]:
    if not year:
        return None, None
    m = _YEAR_RE.match(year.strip())
    if not m:
        return None, None
    a = int(m.group(1))
    return a, int(m.group(2) or a)


def _loose(s: Any) -> str:
    """Назва повіту → форма, стійка до різнобою транскрипції.

    🔴 Виміряно на ЦДІАК ф.224: заголовки описів пишуть повіт ДВОМА способами —
    «Ольгопільський» (73 справи) і «Ольгопільский» (42), — тож точний підрядок
    віддавав 73 зі 115 і мовчав про решту 42. Серед загублених були всі три
    метричні книги Старої Горячківки 1771-1802, тобто саме те село, звідки
    тягнеться відкрите питання роду. Пошук, який пропускає ТРЕТИНУ повіту й не
    каже про це, гірший за відсутній: його нуль читають як негатив.

    Зводимо м'який знак і взаємозамінні и/і/ї — цього досить на різнобій
    «-ський/-ский». Пари з різним КОРЕНЕМ («Проскурівський» ↔ «Проскуровський»)
    так не зводяться; це інша вада, і вона тут свідомо не лікується.
    """
    out = str(s or "").lower().replace("ь", "")
    return out.replace("і", "и").replace("ї", "и")


def filter_rows(rows: list[dict[str, Any]], *, opys: str = "", q: str = "", surname: str = "",
                year: str = "", uezd: str = "", scan: bool = False,
                on_disk: bool = False, todo: bool = False, fs: bool = False,
                state: str = "",
                flag: str = "", live: dict[tuple[str, str, str], str] | None = None,
                status: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Єдиний фільтр реєстру опису.

    `scan`/`on_disk`/`todo` — булеві прапорці CLI; `state` — те саме одним
    значенням для UI. Обидва входи дають той самий результат.
    """
    yf, yt = _year_bounds(year)
    ql, sl = q.lower().strip(), surname.lower().strip()
    ul = _loose(uezd)
    want_flags = {x.strip() for x in (flag or "").split(",") if x.strip()}
    live = live if live is not None else {}
    status = status or {}

    def keep(r: dict[str, Any]) -> bool:
        if opys and (r.get("opys") or "") != opys:
            return False
        if ql:
            hay = " ".join(str(r.get(k) or "") for k in
                           ("title", "title_alt", "commons_title", "surnames"))
            if ql not in hay.lower():
                return False
        if sl and sl not in str(r.get("surnames") or "").lower():
            return False
        if ul and ul not in _loose(r.get("title")):
            return False
        # 🎞 FS — окремий канал доступу, а не різновид «скану»: плівка не лежить
        # файлом на Commons, її дивляться/качають за DGS. Для ф.315 це 12 794
        # справи проти 882 зі сканом, тобто головний спосіб дістати документ.
        if fs and not (r.get("fs_dgs") or r.get("fs_film")):
            return False
        if scan and not (r.get("commons_url") or r.get("mirror_url")):
            return False
        st = status.get(r["shifra"]) or row_status(r, live, {})
        if on_disk and not (r.get("on_disk") or st["on_disk_live"]):
            return False
        if todo and st["disk_state"] != "todo":
            return False
        # `state=scan` — не стан диска, а «десь є оцифроване»: справа може бути
        # ще не завантаженою, але вже мати скан на Commons чи дзеркалі. Тому
        # умова читається як одне ціле, а не як виняток усередині фільтра.
        if (state and st["disk_state"] != state
                and not (state == "scan"
                         and (r.get("commons_url") or r.get("mirror_url")))):
            return False
        if want_flags and not want_flags.issubset(set(st["flags"])):
            return False
        # Обидві межі перевіряються разом: `_year_bounds` віддає їх ПАРОЮ —
        # або обидві, або жодної. Перевіряти лише нижню означало б лишити
        # порівняння з None на випадок, якого сьогодні немає, але який
        # зʼявиться від першої ж зміни в тій функції.
        if yf is not None and yt is not None:
            a = str(r.get("year_from") or "")
            b = str(r.get("year_to") or a)
            if not a.isdigit():
                return False
            if int(b or a) < yf or int(a) > yt:
                return False
        return True

    return [r for r in rows if keep(r)]


# ── зведення й фасети ─────────────────────────────────────────────────────────

def summarize(rows: list[dict[str, Any]],
              live: dict[tuple[str, str, str], str] | None = None) -> dict[str, Any]:
    live = live if live is not None else {}
    s = {"rows": len(rows), "commons": 0, "mirror_only": 0, "truncated": 0,
         "on_disk": 0, "on_disk_live": 0, "todo": 0, "order": 0,
         "interp": 0, "lo": 0, "no_title": 0, "title_conflict": 0,
         "with_title": 0, "with_surnames": 0, "letters": 0}
    for r in rows:
        st = row_status(r, live, {})
        if r.get("commons_url"):
            s["commons"] += 1
        elif r.get("mirror_url"):
            s["mirror_only"] += 1
        if r.get("truncated_mirror"):
            s["truncated"] += 1
        if r.get("on_disk"):
            s["on_disk"] += 1
        if st["on_disk_live"]:
            s["on_disk_live"] += 1
        if st["disk_state"] == "todo":
            s["todo"] += 1
        if st["disk_state"] == "order":
            s["order"] += 1
        if "interp" in st["flags"]:
            s["interp"] += 1
        if "lo" in st["flags"]:
            s["lo"] += 1
        if "no_title" in st["flags"]:
            s["no_title"] += 1
        else:
            s["with_title"] += 1
        if "title_conflict" in st["flags"]:
            s["title_conflict"] += 1
        if r.get("surnames"):
            s["with_surnames"] += 1
        if r.get("spr_letter"):
            s["letters"] += 1
    return s


_UEZD_RE = re.compile(
    r"(Балтск|Ольгопольск|Каменецк|Проскуровск|Летичевск|Литинск|Винницк|"
    r"Брацлавск|Гайсинск|Ямпольск|Могилевск|Ушицк)", re.IGNORECASE)
_UEZD_LABEL = {"балтск": "Балтський", "ольгопольск": "Ольгопільський",
               "каменецк": "Кам'янецький", "проскуровск": "Проскурівський",
               "летичевск": "Летичівський", "литинск": "Літинський",
               "винницк": "Вінницький", "брацлавск": "Брацлавський",
               "гайсинск": "Гайсинський", "ямпольск": "Ямпільський",
               "могилевск": "Могилівський", "ушицк": "Ушицький"}


def facets(rows: list[dict[str, Any]]) -> dict[str, Any]:
    opys_c: dict[str, int] = {}
    uezd_c: dict[str, int] = {}
    for r in rows:
        o = r.get("opys") or ""
        if o:
            opys_c[o] = opys_c.get(o, 0) + 1
        m = _UEZD_RE.search(r.get("title") or "")
        if m:
            lbl = _UEZD_LABEL.get(m.group(1).lower(), m.group(1))
            uezd_c[lbl] = uezd_c.get(lbl, 0) + 1
    return {
        "opys": [{"code": k, "n": v} for k, v in
                 sorted(opys_c.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0)],
        "uezd": [{"code": k, "n": v} for k, v in
                 sorted(uezd_c.items(), key=lambda kv: -kv[1])],
    }


def surname_list(fond_id: str, limit: int = 400) -> list[str]:
    """Найчастіші прізвища з алфавітки — для `<datalist>` у фільтрі."""
    rows = load_alfavitka(fond_id)
    if not rows:
        return []
    seen: dict[str, int] = {}
    for r in rows:
        n = (r.get("surname") or "").strip()
        if n:
            seen[n] = seen.get(n, 0) + 1
    return [k for k, _ in sorted(seen.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]


# ── одна справа ───────────────────────────────────────────────────────────────

def parse_key(key: str) -> tuple[str, str, str, str, str]:
    """`DAHMO/230/43` або `ДАХмО 230-1-43` → (repo, fond, opys, spr_int, letter)."""
    m = _KEY_RE.match(key.strip())
    if not m:
        raise ValueError(f"не розумію ключ «{key}». Приклади: DAHMO/230/43, "
                         "DAHMO/230/1/43")
    repo = m.group(1).upper()
    repo = {"ДАХМО": "DAHMO", "ЦДІАК": "CDIAK", "ДАВІО": "DAVIO",
            "ДАВО": "DAVO"}.get(repo, repo)
    return repo, m.group(2), (m.group(3) or "1"), m.group(4), (m.group(5) or "").lower()


def fond_id_of(repo: str, fond: str) -> str:
    return f"{REPO_SLUG.get(repo.upper(), repo.lower())}_{fond}"


def registry_row(repo: str, fond: str, opys: str, spr: str,
                 letter: str = "") -> tuple[dict[str, Any] | None, Path]:
    """Нормалізований рядок однієї справи + шлях реєстру (для повідомлень)."""
    fond_id = fond_id_of(repo, fond)
    path = fond_path(fond_id)
    if not path.exists():
        return None, path
    for r in load_rows(fond_id):
        if (r.get("opys") == opys and r.get("spr_int") == spr
                and (r.get("spr_letter") or "") == (letter or "")):
            return r, path
    return None, path
