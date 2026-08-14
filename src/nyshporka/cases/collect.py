r"""Збірка реєстру: опис бібліотеки + чотири шари обробки.

Кожен шар читає ті самі файли, що й конвеєр, і нічого не переобчислює власною
логікою — друга правда про стан справи розійшлася б із першою тихо.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict

from nyshporka.cases.geo import (
    geo_blob,
    guberniya_by_fond,
    match_place_id,
    parse_place,
    settlement_from_title,
)
from nyshporka.cases.model import CaseRow
from nyshporka.cases.resolve import (
    LibraryIndex,
    bundles,
    parse_slug_case,
    resolve_run,
    slug_case,
)
from nyshporka.library import (
    _DEFAULT_OPYS,
    _REPO_LABEL,
    ROOT,
    load_verdicts,
    parse_source_id,
)

HTR_ROOT = ROOT / "reports" / "htr"
RAW_DIR = ROOT / "data" / "raw"
PAGES_ROOT = ROOT / "data" / "pages"
CLAN_STATE = ROOT / "data" / "clan_hunt" / "state.json"
DERIVED_DB = ROOT / "data" / "derived" / "nyshporka.sqlite"

_IMG_EXT = {".jpg", ".jpeg", ".png"}
#: Теки-не-справи (періодика за роками, описи фондів) — як у `library._SKIP_SLUGS`.
_SKIP_SLUGS = {"davo_opysy", "dahmo_319_f65_opisy", "bev_pdh", "kev_pdh",
               "khev_pdh", "eev_pdh", "_console_pages"}

#: Аркуш у цитаті: «253» або «253-255». Рік у чотири цифри аркушем не вважаємо.
_PAGE_ONE_RE = re.compile(r"^\s*(\d{1,5})\s*$")
_PAGE_RANGE_RE = re.compile(r"^\s*(\d{1,5})\s*[-–]\s*(\d{1,5})\s*$")
_SCAN_IN_TEXT_RE = re.compile(r"скан[иі]?\s*([0-9,\s/і-]{3,40})", re.IGNORECASE)
_NUMS_RE = re.compile(r"[0-9]{3,5}")
_MAX_RANGE = 300


def _model_voice(model: str, engine: str) -> list[tuple[str, str]]:
    """Поле `model` прогону → голоси, які в ньому брали участь.

    Ансамбль пишеться одним рядком (`pysar_cyr_v17.pt+diak_v4`), тож без розбору
    другий голос зникав би з обліку. Письмо каже ПРЕФІКС імені, не розширення:
    `skryba_*` — латинка, `diak_*` — кирилиця, обидва kraken.
    """
    out: list[tuple[str, str]] = []
    for part in re.split(r"[+,]", model or ""):
        p = part.strip()
        if not p:
            continue
        low = p.lower()
        if low.startswith("pysar"):
            out.append(("pysar", p))
        elif low.startswith("diak"):
            out.append(("diak", p))
        elif low.startswith("skryba"):
            out.append(("skryba", p))
        elif engine == "parseq":
            out.append(("pysar", p))
        elif engine == "kraken":
            out.append(("diak", p))
    return out


def _iter_htr_runs():
    """(ім'я прогону, мета) для кожної теки з `_htr_meta.json`."""
    if not HTR_ROOT.is_dir():
        return
    for meta_path in sorted(HTR_ROOT.glob("*/_htr_meta.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(meta, dict):
            yield meta_path.parent.name, meta


def _engine_of(meta: dict) -> str:
    model = str(meta.get("model") or "")
    if ".pt" in model:
        return "parseq"
    if ".mlmodel" in model:
        return "kraken"
    return str(meta.get("engine") or "")


def _ordered_cases(index: LibraryIndex) -> list[dict]:
    """Теки з карткою справи, але БЕЗ кадрів — «замовлено, не завантажено».

    Бібліотека їх не бачить за побудовою (вимагає зображень або PDF), і саме через
    це сім справ ДАОО по парафії Фараонівка не потрапили у вчорашню інвентаризацію.
    """
    out: list[dict] = []
    if not RAW_DIR.is_dir():
        return out
    seen: set[str] = set()
    for depth in ("*/*", "*/*/*", "*/*/*/*"):
        for d in sorted(RAW_DIR.glob(depth)):
            if not d.is_dir() or d.name.startswith("_"):
                continue
            try:
                if d.relative_to(RAW_DIR).parts[0] in _SKIP_SLUGS:
                    continue
            except ValueError:
                continue
            rel = str(d.relative_to(ROOT)).replace("\\", "/")
            if rel in seen or rel in index.by_path:
                continue
            sidecar = next((d / n for n in ("_source.json", "meta.json")
                            if (d / n).is_file()), None)
            if sidecar is None:
                continue
            if any(p.suffix.lower() in _IMG_EXT or p.suffix.lower() == ".pdf"
                   for p in d.iterdir() if p.is_file()):
                continue                      # матеріал є → це справа бібліотеки
            try:
                meta = json.loads(sidecar.read_text(encoding="utf-8"))
            except Exception:
                continue
            seen.add(rel)
            out.append({"rel": rel, "meta": meta})
    return out


def _count_frames(rel: str | None) -> int:
    """Кадри (або PDF) прямо в теці; для файла-PDF — 1."""
    if not rel:
        return 0
    p = ROOT / rel
    if p.is_file():
        return 1 if p.suffix.lower() in _IMG_EXT | {".pdf"} else 0
    if not p.is_dir():
        return 0
    n = 0
    try:
        for f in p.iterdir():
            if f.is_file() and f.suffix.lower() in _IMG_EXT | {".pdf"}:
                n += 1
    except OSError:
        return n
    return n


def _best_frames(row_paths: list[str | None]) -> int:
    """Найповніша тека справи.

    🔴 Справа часто лежить у кількох теках — оригінальні кадри, зменшені копії для
    хмари, посторінковий рендер PDF. Бібліотека рахує кадри лише по ПЕРШІЙ, і на
    ДАХмО 315-1-7864 це давало «3 кадри» (тека з PDF) при 3773 сторінках рендеру:
    покриття декоду виходило безглуздим, а «декод обірвано» — випадковим.
    """
    return max((_count_frames(p) for p in row_paths if p), default=0)


def _unfiled_material(index: LibraryIndex, known: set[str]) -> list[tuple[str, int]]:
    """Теки з кадрами, які НЕ вдалось звести до жодної справи → [(rel, кадрів)].

    🔴 Це не дрібниця обліку: 14 плівок ANRM ф.211 (13 535 кадрів) лежать на диску
    з сайдкаром, у якому є номер плівки, але немає шифри справи. Бібліотека їх не
    бачить за побудовою (не з чого зробити ключ), тож у будь-якому зведенні вони
    просто зникали — при тому, що це найбільший необроблений масив проєкту.
    """
    out: list[tuple[str, int]] = []
    if not RAW_DIR.is_dir():
        return out
    seen: set[str] = set()
    for depth in ("*", "*/*", "*/*/*", "*/*/*/*"):
        for d in sorted(RAW_DIR.glob(depth)):
            if not d.is_dir() or d.name.startswith("_"):
                continue
            try:
                rel_parts = d.relative_to(RAW_DIR).parts
            except ValueError:
                continue
            if rel_parts[0] in _SKIP_SLUGS:
                continue
            rel = str(d.relative_to(ROOT)).replace("\\", "/")
            if rel in known or rel in seen:
                continue
            if any(rel.startswith(k + "/") for k in known):
                continue                      # підтека вже врахованої справи/збірки
            frames = _count_frames(rel)
            if frames:
                seen.add(rel)
                out.append((rel, frames))
    return out


def _sidecar_near(rel: str) -> dict:
    """Опис справи з сайдкара теки АБО її батьківської теки.

    🔴 Кадри часто лежать у підтеці, а сайдкар — на рівень вище:
    `cdiak_224/spr-864/{meta.json, pages/}`. Шукаючи лише в теці з кадрами, ми
    діставали справу без назви — при тому, що поруч лежить повний опис
    («Метрична книга церкви Благовіщення … м-ка М'ястківка», 1752-1777).
    """
    for base in (ROOT / rel, (ROOT / rel).parent):
        for name in ("_source.json", "meta.json"):
            f = base / name
            if not f.is_file():
                continue
            try:
                m = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            title = str(m.get("title") or "").strip()
            if not title:
                # Сайдкари ДАОО не мають `title` взагалі — опис у них розкладений
                # по полях (`church` + `place`). Без цього складання 13 справ
                # парафії Фараонівка лишались «без назви» при повному описі поруч.
                title = " ".join(x for x in (str(m.get("church") or "").strip(),
                                             str(m.get("place") or "").strip()) if x)
            if not title:
                continue
            # Роки лежать під трьома різними іменами: `dates` (archium),
            # `years` (ДАОО: "1849-1854"), `year_from`/`year_to` (наші сайдкари).
            years = re.findall(r"\b(1[5-9]\d{2}|20\d{2})\b",
                               f'{m.get("dates") or ""} {m.get("years") or ""}')
            yf = _to_year(m.get("year_from")) or _to_year(m.get("year"))
            yt = _to_year(m.get("year_to"))
            if years:
                yf = yf or int(years[0])
                yt = yt or int(years[-1])
            return {"title": title,
                    "doc_type": str(m.get("record_type") or m.get("doc_type") or "").strip(),
                    "year_from": yf, "year_to": yt or yf,
                    "place": str(m.get("place") or m.get("church") or "").strip(),
                    "opys": str(m.get("opys") or m.get("inv") or "").strip().lstrip("0") or None,
                    "desc_source": "source_json" if name == "_source.json" else "meta_json"}
    return {}


def _to_year(v) -> int | None:
    s = str(v or "").strip()[:4]
    return int(s) if s.isdigit() else None


def _clan_runs() -> dict[str, dict]:
    try:
        return json.loads(CLAN_STATE.read_text(encoding="utf-8")).get("runs", {})
    except Exception:
        return {}


def _pages_counts() -> dict[str, tuple[int, int]]:
    """key справи → (сторінок занесено, з них `full`) зі сховища `data/pages/**`."""
    out: dict[str, tuple[int, int]] = {}
    if not PAGES_ROOT.is_dir():
        return out
    for f in sorted(PAGES_ROOT.glob("*/*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        key = str(data.get("case") or data.get("key") or "").strip()
        if not key:
            repo = f.parent.name.upper()
            stem = f.stem.split("-")
            if len(stem) == 2:
                key = f"{repo}/{stem[0]}/{stem[1]}"
        pages = data.get("pages")
        if isinstance(pages, dict):
            items = list(pages.values())
        elif isinstance(pages, list):
            items = pages
        else:
            items = []
        full = sum(1 for p in items if isinstance(p, dict) and p.get("status") == "full")
        if key:
            prev = out.get(key, (0, 0))
            out[key] = (prev[0] + len(items), prev[1] + full)
    return out


def _canon_counts() -> dict[str, dict]:
    """source_id → {facts, persons, scans}. Читає derived-базу, не canonical MD.

    🔴 Аркуші рахуються з `citations.page` **і** з тексту цитати/примітки («спр.99
    скан 0123»): канон ховає номери сканів не лише в `page`, і облік лише по ньому
    показував 32 аркуші з 75 (memory `clan-search-registry-and-anchors`).
    `media[]` тут НЕ враховано — вона не має `source_id`, тож прив'язка до справи
    була б здогадом; це відома неповнота, а не забутий шар.
    """
    out: dict[str, dict] = {}
    if not DERIVED_DB.is_file():
        return out
    try:
        con = sqlite3.connect(f"file:{DERIVED_DB}?mode=ro", uri=True)
    except sqlite3.Error:
        return out
    try:
        rows = con.execute(
            "SELECT c.source_id, f.person_id, c.page, c.quote, c.note "
            "FROM citations c JOIN facts f ON f.id = c.fact_id").fetchall()
    except sqlite3.Error:
        return out
    finally:
        con.close()
    agg: dict[str, dict] = defaultdict(
        lambda: {"facts": 0, "persons": set(), "scans": set()})
    for source_id, person_id, page, quote, note in rows:
        if not source_id:
            continue
        a = agg[source_id]
        a["facts"] += 1
        if person_id:
            a["persons"].add(person_id)
        page_raw = str(page or "")
        mr = _PAGE_RANGE_RE.match(page_raw)
        if mr:
            lo, hi = int(mr.group(1)), int(mr.group(2))
            if 0 < hi - lo <= _MAX_RANGE:
                a["scans"].update(range(lo, hi + 1))
            else:
                a["scans"].add(lo)
        elif _PAGE_ONE_RE.match(page_raw):
            a["scans"].add(int(page_raw.strip()))
        blob = " ".join(str(x or "") for x in (page, quote, note))
        for grp in _SCAN_IN_TEXT_RE.findall(blob):
            for s in _NUMS_RE.findall(grp):
                if len(s) == 4 and 1700 <= int(s) <= 2100:
                    continue                      # це рік, не скан
                a["scans"].add(int(s))
    for sid, a in agg.items():
        out[sid] = {"facts": a["facts"], "persons": len(a["persons"]),
                    "scans": len(a["scans"])}
    return out


#: Нижче цієї частки прочитаних кадрів прогін вважається обірваним. Поріг щільний
#: свідомо: 1271 сторінка з 1297 (ДАХмО 315-1-11817) — це 26 непрочитаних аркушів,
#: тобто рівно той випадок, заради якого стан і заводився. Пропуск в один-два кадри
#: (обкладинка, брак зйомки) на 0.99 ще не спрацьовує.
_COVERAGE_OK = 0.99


def _htr_stage(row: CaseRow) -> str:
    if not (row.htr_pysar or row.htr_diak or row.htr_skryba):
        return "none"
    if row.frames and row.htr_pages_max < row.frames * _COVERAGE_OK:
        return "partial"
    if row.htr_pysar and (row.htr_diak or row.htr_skryba):
        return "both"
    return "pysar" if row.htr_pysar else ("diak" if row.htr_diak else "skryba")


def _fuzzy_stage(row: CaseRow) -> str:
    """Стан пошуку роду за зростанням повноти: none → scanned → reviewed → swept.

    ⚠ `swept` (суцільне чесання всіма каналами) стоїть ВИЩЕ за `reviewed`: це
    сильніша заява про покриття, і справа з вердиктами всередині прочесаного
    заходу мусить лишатись прочесаною. Спершу було навпаки, і дві з чотирнадцяти
    прочесаних справ ф.315 випадали з фільтра «прочесано».
    """
    if not row.fuzzy_scanned:
        return "none"
    if row.fuzzy_swept:
        return "swept"
    return "reviewed" if row.fuzzy_reviewed else "scanned"


def collect_rows(index: LibraryIndex | None = None) -> tuple[list[CaseRow], list]:
    """Зібрати реєстр. Повертає (рядки справ, нерозв'язані прив'язки прогонів)."""
    idx = index or LibraryIndex()
    rows: dict[str, CaseRow] = {}
    for e in idx.rows:
        key = e.get("key")
        if not key or key in rows:
            continue
        frames = int(e.get("frames") or 0)
        if e.get("extra_paths"):
            frames = max(frames, _best_frames([e.get("path"), *(e.get("extra_paths") or [])]))
        rows[key] = CaseRow(
            key=key, shifra=e.get("shifra") or "", repo=e.get("repo"),
            repo_label=e.get("repo_label"), fond=e.get("fond"), opys=e.get("opys"),
            spr=e.get("spr"), title=e.get("title") or "",
            doc_type=e.get("doc_type") or "",
            record_types=list(e.get("record_types") or []),
            year_from=e.get("year_from"), year_to=e.get("year_to"),
            place_raw=e.get("place") or "", parish=e.get("parish"),
            script=e.get("script") or "", desc_source=e.get("desc_source") or "code",
            path=e.get("path"), extra_paths=list(e.get("extra_paths") or []),
            frames=frames, state="on_disk" if frames else "ordered",
            canon_source_id=e.get("source_id"),
            curated=bool(e.get("curated")), group=e.get("group"), why=e.get("why"),
        )

    # ── замовлене: картка справи без кадрів ─────────────────────────────────
    for item in _ordered_cases(idx):
        meta, rel = item["meta"], item["rel"]
        shifra = str(meta.get("shifra") or "").strip()
        parsed = None
        m = re.search(r"(\d+)\s*[-–]\s*(\d+)\s*[-–]\s*(\w+)", shifra)
        if m:
            repo = (re.split(r"[\s\d]", shifra, maxsplit=1)[0] or "").upper() or None
            parsed = (repo, m.group(1).lstrip("0"), m.group(2).lstrip("0"),
                      m.group(3).lstrip("0"))
        if not parsed or not parsed[0]:
            continue
        key = f"{parsed[0]}/{parsed[1]}/{parsed[3]}"
        if key in rows:
            rows[key].state = rows[key].state or "ordered"
            continue
        yf = meta.get("year_from") or meta.get("year")
        rows[key] = CaseRow(
            key=key, shifra=shifra or key, repo=parsed[0], repo_label=parsed[0],
            fond=parsed[1], opys=parsed[2], spr=parsed[3],
            title=str(meta.get("title") or "").strip(),
            doc_type=str(meta.get("record_type") or meta.get("doc_type") or "").strip(),
            year_from=int(str(yf)[:4]) if str(yf or "").strip()[:4].isdigit() else None,
            year_to=(int(str(meta.get("year_to"))[:4])
                     if str(meta.get("year_to") or "").strip()[:4].isdigit() else None),
            place_raw=str(meta.get("place") or meta.get("church") or "").strip(),
            path=rel, frames=0, state="ordered", desc_source="source_json",
            expected=meta.get("frames") if isinstance(meta.get("frames"), int) else None,
        )

    # ── збірки: одиниці роботи, які архівною справою не є ───────────────────
    for key, b in bundles().items():
        rel = str(b.get("path") or "")
        frames = 0
        d = ROOT / rel if rel else None
        if d is not None and d.is_dir():
            frames = sum(1 for p in d.iterdir()
                         if p.is_file() and p.suffix.lower() in _IMG_EXT)
        rows[key] = CaseRow(
            key=key, kind="bundle", shifra=str(b.get("label") or key),
            repo=b.get("repo"), repo_label=b.get("repo_label") or b.get("repo"),
            fond=b.get("fond"), spr=key.rsplit("/", 1)[-1],
            title=str(b.get("label") or ""), doc_type=str(b.get("doc_type") or ""),
            place_raw=str(b.get("place") or ""), path=rel or None, frames=frames,
            state="on_disk" if frames else "ordered", desc_source="override",
            why=str(b.get("why") or ""),
        )

    # ── матеріал на диску, який не звівся до справи ─────────────────────────
    known_paths = set(idx.by_path)
    known_paths.update(r.path for r in rows.values() if r.path)
    for rel, frames in _unfiled_material(idx, known_paths):
        # Спершу пробуємо звести теку до вже відомої справи: рендери й зменшені
        # копії (`dahmo_315_pages/spr-7864`) — це той самий матеріал, а не новий.
        hit = slug_case(rel, idx)
        if hit and hit in rows:
            row = rows[hit]
            if rel != row.path and rel not in row.extra_paths:
                row.extra_paths.append(rel)
            if frames > row.frames:
                row.frames = frames
                row.state = "on_disk"
            continue
        # Шифра з теки читається, але справи такої бібліотека не знає — заводимо
        # її САМІ. Інакше ЦДІАК 224-1-864/865 (метрики М'ястківки 1752-1791)
        # лишились би «матеріалом без шифри», хоч номер справи стоїть в імені теки.
        parsed = parse_slug_case(rel)
        if parsed and parsed[1] and parsed[3]:
            repo, fond, opys, spr = parsed
            key = f"{repo}/{fond}/{spr}"
            if key in rows:
                row = rows[key]
                if rel != row.path and rel not in row.extra_paths:
                    row.extra_paths.append(rel)
                row.frames = max(row.frames, frames)
                continue
            side = _sidecar_near(rel)
            opys = opys or side.get("opys") or _DEFAULT_OPYS.get((repo, fond))
            label = _REPO_LABEL.get(repo, repo)
            rows[key] = CaseRow(
                key=key, repo=repo, repo_label=label, fond=fond, opys=opys, spr=spr,
                shifra=f"{label} {fond}-{opys}-{spr}" if opys else f"{label} {fond}-{spr}",
                title=side.get("title", ""), doc_type=side.get("doc_type", ""),
                year_from=side.get("year_from"), year_to=side.get("year_to"),
                place_raw=side.get("place", ""),
                path=rel, frames=frames, state="on_disk",
                desc_source=side.get("desc_source", "disk"),
                why=("шифру взято з імені теки" if not side.get("title")
                     else "опис із сайдкара теки; у каталогах бібліотеки справи немає"),
            )
            continue
        key = f"@disk/{rel}"
        name = rel.rsplit("/", 1)[-1]
        repo = rel.split("/")[2].split("_")[0].upper() if len(rel.split("/")) > 2 else ""
        rows[key] = CaseRow(
            key=key, kind="unfiled", shifra=f"без шифри · {name}",
            repo=repo or None, repo_label=repo or None,
            title="", path=rel, frames=frames, state="on_disk",
            desc_source="disk",
            why="матеріал на диску без шифри справи — сайдкар не несе фонд/справу",
        )

    orphans: list = []

    # 🔴 Прогін пошуку роду й HTR-прогін — ОДНА Й ТА САМА тека `reports/htr/<run>`,
    # тож і справа в них мусить бути одна. Доти HTR-гілка резолвилась із `case_dir`
    # і `case_key` мети, а clan-гілка нижче — ЛИШЕ з імені прогону, і вони
    # розходились: `kostel-dazho-178-51-418-1839` (ДАЖО 178-51-418, у бібліотеці
    # лежить під теками костелу) HTR-гілкою ліг у свою справу, а clan-гілкою — у
    # чужу. Наслідок найгірший з можливих для реєстру: справа, по якій пошук
    # ПРОЙДЕНО, показувала «пошук роду: —», тобто прилад брехав саме про те,
    # заради чого існує. Тому підказки мети збираються один раз і йдуть в обидві
    # гілки.
    run_meta_hint: dict[str, tuple[str, str]] = {}

    # ── HTR ─────────────────────────────────────────────────────────────────
    for name, meta in _iter_htr_runs():
        run_meta_hint[name] = (str(meta.get("case_dir") or ""),
                               str(meta.get("case_key") or ""))
        link = resolve_run(name, str(meta.get("case_dir") or ""), idx,
                           meta_key=str(meta.get("case_key") or ""))
        pages = len(meta.get("pages") or {})
        if not link.key or link.key not in rows:
            orphans.append({"run": name, "case_dir": link.case_dir, "pages": pages,
                            "model": meta.get("model") or "",
                            "resolved_by": link.resolved_by, "note": link.note,
                            "key": link.key})
            continue
        row = rows[link.key]
        row.htr_runs.append(name)
        row.htr_pages_max = max(row.htr_pages_max, pages)
        upd = str(meta.get("updated") or "")
        if upd > row.htr_updated:
            row.htr_updated = upd
        for voice, model in _model_voice(str(meta.get("model") or ""), _engine_of(meta)):
            setattr(row, f"htr_{voice}", True)
            if pages >= getattr(row, f"htr_{voice}_pages"):
                setattr(row, f"htr_{voice}_pages", pages)
                setattr(row, f"htr_{voice}_model", model)

    # ── fuzzy-пошук роду ────────────────────────────────────────────────────
    for name, run in _clan_runs().items():
        hint_dir, hint_key = run_meta_hint.get(name, ("", ""))
        link = resolve_run(name, hint_dir, idx, meta_key=hint_key)
        if not link.key or link.key not in rows:
            orphans.append({"run": name, "case_dir": "", "pages": run.get("pages_decoded"),
                            "model": run.get("model") or "", "source": "clan_hunt",
                            "resolved_by": link.resolved_by, "note": link.note,
                            "key": link.key})
            continue
        row = rows[link.key]
        row.fuzzy_runs.append(name)
        scanned = str(run.get("scanned") or "")
        if scanned >= row.fuzzy_scanned:
            row.fuzzy_scanned = scanned
            row.fuzzy_model = str(run.get("model") or "")
        row.fuzzy_pages = max(row.fuzzy_pages, int(run.get("pages_decoded") or 0))
        row.fuzzy_hits = max(row.fuzzy_hits, len(run.get("pages_new_strong") or []))
        row.fuzzy_reviewed = max(row.fuzzy_reviewed, len(run.get("reviewed") or {}))
        if any(k.startswith("swept_") for k in run):
            row.fuzzy_swept = True

    # ── канон ───────────────────────────────────────────────────────────────
    canon = _canon_counts()
    by_case_sid: dict[str, list[str]] = defaultdict(list)
    for sid in canon:
        parsed = parse_source_id(sid)
        if parsed:
            by_case_sid[f"{parsed[0]}/{parsed[1]}/{parsed[3]}"].append(sid)
    for key, sids in by_case_sid.items():
        row = rows.get(key)
        if not row:
            continue
        row.canon_facts = sum(canon[s]["facts"] for s in sids)
        row.canon_persons = max(canon[s]["persons"] for s in sids)
        row.canon_scans = sum(canon[s]["scans"] for s in sids)
        row.canon_source_id = row.canon_source_id or sids[0]

    # ── око ─────────────────────────────────────────────────────────────────
    for key, (noted, full) in _pages_counts().items():
        row = rows.get(key)
        if row:
            row.pages_noted, row.pages_full = noted, full

    # ── людські вердикти ────────────────────────────────────────────────────
    for key, v in load_verdicts().items():
        row = rows.get(key)
        if row:
            row.verdict = str(v.get("verdict") or "")
            row.verdict_note = str(v.get("note") or "")

    # ── дозаповнення опису із сайдкара ──────────────────────────────────────
    # Бібліотека бере назву лише з поля `title`, а сайдкари ДАОО описують справу
    # полями `church`+`place` — тож 13 справ парафії Фараонівка стояли «без назви»
    # при повному описі поруч. Дозаповнюємо ЛИШЕ порожнє, нічого не перезаписуючи.
    for row in rows.values():
        if row.title or not row.path:
            continue
        side = _sidecar_near(row.path)
        if not side:
            continue
        row.title = side.get("title", "")
        row.doc_type = row.doc_type or side.get("doc_type", "")
        row.year_from = row.year_from or side.get("year_from")
        row.year_to = row.year_to or side.get("year_to")
        row.place_raw = row.place_raw or side.get("place", "")
        if row.desc_source in ("code", "disk"):
            row.desc_source = side.get("desc_source", row.desc_source)

    # ── географія ───────────────────────────────────────────────────────────
    for row in rows.values():
        # Парафія з канону — теж поселення: у метричних справах саме вона називає
        # село, а `place` буває лише повітом.
        geo = parse_place(row.place_raw or row.parish or "")
        if row.parish and row.parish not in geo["settlements"]:
            extra = parse_place(row.parish)
            for s in extra["settlements"]:
                if s not in geo["settlements"]:
                    geo["settlements"].append(s)
        # Поля місця немає — але назва справи його часто несе («Сповідальні
        # відомості церков Ольгопільського повіту»). Беремо звідти ЛИШЕ повіт і
        # губернію: назва згадує десяток сіл, і будь-яке з них як «головне
        # поселення» було б вигадкою, а повіт у заголовку однозначний.
        if not geo["uezds"] and row.title:
            from_title = parse_place(row.title)
            geo["uezds"] = from_title["uezds"]
            geo["guberniya"] = geo["guberniya"] or from_title["guberniya"]
        if not geo["settlements"] and row.title:
            one = settlement_from_title(row.title)
            if one:
                geo["settlements"] = [one]
        row.settlements = geo["settlements"]
        row.uezds = geo["uezds"]
        # Губернія фонду — запасний варіант: розібране з тексту сильніше.
        row.guberniya = geo["guberniya"] or guberniya_by_fond(row.repo, row.fond)
        row.settlement = geo["settlements"][0] if geo["settlements"] else ""
        row.uezd = geo["uezds"][0] if geo["uezds"] else ""
        row.place_id = match_place_id(geo["settlements"])
        row.geo_blob = geo_blob(geo["settlements"], geo["uezds"], geo["guberniya"],
                                geo["alt_names"])

    for row in rows.values():
        if row.frames and row.htr_pages_max and row.htr_pages_max < row.frames * _COVERAGE_OK:
            row.state = "partial"
        row.htr_stage = _htr_stage(row)
        row.fuzzy_stage = _fuzzy_stage(row)

    return sorted(rows.values(), key=lambda r: (r.repo_label or "", r.fond or "",
                                                int(re.sub(r"\D", "", r.spr or "0") or 0))), orphans
