r"""Збірка реєстру: опис бібліотеки + чотири шари обробки.

Кожен шар читає ті самі файли, що й конвеєр, і нічого не переобчислює власною
логікою — друга правда про стан справи розійшлася б із першою тихо.
"""
from __future__ import annotations

import copy
import json
import os
import re
import sqlite3
from collections import defaultdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

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
from nyshporka.cases.walk import IMG_EXT, frame_names
from nyshporka.library import (
    _DEFAULT_OPYS,
    _REPO_LABEL,
    ROOT,
    _mk_key,
    _pdf_pages,
    _sidecar_opys,
    candidate_keys,
    claim_collision,
    load_verdicts,
    opys_conflict,
    parse_source_id,
    skip_slugs,
    split_into,
)

HTR_ROOT = ROOT / "reports" / "htr"
RAW_DIR = ROOT / "data" / "raw"
PAGES_ROOT = ROOT / "data" / "pages"
CLAN_STATE = ROOT / "data" / "clan_hunt" / "state.json"
DERIVED_DB = ROOT / "data" / "derived" / "nyshporka.sqlite"

#: Які файли теки — кадри, і які з них ідуть у знаменник, вирішує
#: `cases.walk` (`IMG_EXT`, `frame_names`): одне правило для обходу, прямого
#: читання теки, збірок і сховища сторінок (аудит 29.09.2026).
#: Теки-не-справи беруться з `library.skip_slugs()` — вбудований перелік разом із
#: паком. ⚠ Тут лежала друга копія набору, і вона так само не знала паку.

#: Аркуш у цитаті: «253» або «253-255». Рік у чотири цифри аркушем не вважаємо.
_PAGE_ONE_RE = re.compile(r"^\s*(\d{1,5})\s*$")
_PAGE_RANGE_RE = re.compile(r"^\s*(\d{1,5})\s*[-–]\s*(\d{1,5})\s*$")
_SCAN_IN_TEXT_RE = re.compile(r"скан[иі]?\s*([0-9,\s/і-]{3,40})", re.IGNORECASE)
_NUMS_RE = re.compile(r"[0-9]{3,5}")
_MAX_RANGE = 300


def _model_voice(model: str, engine: str) -> list[tuple[str, str]]:
    """Поле `model` прогону → голоси, які в ньому брали участь.

    Ансамбль пишеться одним рядком (`pysar_cyr_v17.pt+diak_v4`), тож без розбору
    другий голос зникав би з обліку. Письмо каже префікс імені, не розширення:
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


def _volume(pages: dict[str, Any]) -> tuple[int, int, int]:
    """Обсяг одного прогону: (символів, рядків, сторінок без жодного символу).

    Числа беруться з мети прогону, а не перечитуванням `*.txt`: рушій кладе
    `chars`/`lines` на кожну сторінку сам, покриття суцільне, і прохід по метах
    коштує 1196 файлів замість 454 тисяч.

    Порожньою вважається рівно `chars == 0` — «рушій не видав нічого». Порога
    на кшталт «менше десяти символів» тут навмисно немає: він оголосив би
    порожніми й ті сторінки, де прочитано самий колонтитул, а це вже не факт
    про рушій, а здогад про вміст аркуша.
    """
    chars = lines = blank = 0
    for v in pages.values():
        if not isinstance(v, dict):
            continue
        c = int(v.get("chars") or 0)
        chars += c
        lines += int(v.get("lines") or 0)
        blank += not c
    return chars, lines, blank


#: Файл шару, який збірка не змогла прочитати: `{"path": …, "why": …}`.
Unreadable = dict[str, str]


def _note_unreadable(sink: list[Unreadable] | None, path: Any, why: object) -> None:
    """Записати нечитаний файл шару — щоб збірка сказала про нього вголос.

    🔴 Аудит 29.09.2026: тут стояло `except Exception: continue`, і битий файл
    просто зникав. Реєстр після цього відповідав «ока не було», «пошуку не
    було» — а один пошкоджений `clan_hunt/state.json` давав `fuzzy_stage=none`
    УСІМ справам. Мовчки неповний реєстр виглядає як відповідь, тож він гірший
    за відсутній. Збірку один файл не валить, але й не проходить непоміченим.
    """
    if sink is None:
        return
    try:
        rel = str(os.path.relpath(path, ROOT)).replace("\\", "/")
    except ValueError:
        rel = str(path)
    reason = f"{type(why).__name__}: {why}" if isinstance(why, BaseException) else str(why)
    sink.append({"path": rel, "why": reason})


def _iter_htr_runs(unreadable: list[Unreadable] | None = None,
                   ) -> Iterator[tuple[str, dict[str, Any]]]:
    """(ім'я прогону, мета) для кожної теки з `_htr_meta.json`.

    Нечитана мета йде в `unreadable`, а не в тишу: інакше прогін зникає, і
    справа стоїть у реєстрі «без декоду» (аудит 29.09.2026).
    """
    if not HTR_ROOT.is_dir():
        return
    for meta_path in sorted(HTR_ROOT.glob("*/_htr_meta.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception as exc:
            _note_unreadable(unreadable, meta_path, exc)
            continue
        if not isinstance(meta, dict):
            _note_unreadable(unreadable, meta_path, "мета не є JSON-об'єктом")
            continue
        if meta.get("superseded"):
            # Прогін збірної теки, розкладеної на справи: його сторінки вже
            # лежать прогонами частин, і порахований ще раз він подвоїв би їх.
            continue
        yield meta_path.parent.name, meta


def _engine_of(meta: dict[str, Any]) -> str:
    model = str(meta.get("model") or "")
    if ".pt" in model:
        return "parseq"
    if ".mlmodel" in model:
        return "kraken"
    return str(meta.get("engine") or "")


def _raw_scans() -> list[Any]:
    """Один обхід `data/raw` на всю збірку — замість трьох наборів `glob`-ів.

    ⏱ `_ordered_cases`, `_unfiled_material` і `_count_frames` ходили деревом
    кожен сам: 3+4 `glob`-патерни, кожен згори, плюс `iterdir()` з двома
    системними викликами на кожен кадр. Тут дерево читається раз, і всі три
    беруть із нього готове. Порядок видачі — той самий, що давали `glob`-и
    (див. `cases.walk`), тож зріз не змінюється.
    """
    from nyshporka.cases.walk import walk_root

    if not RAW_DIR.is_dir():
        return []
    return list(walk_root(RAW_DIR, max_depth=4, skip_slugs=skip_slugs()))


#: код архіву кирилицею → латинський код репозиторію (як у `fonds.registry`).
#: Паспорти справ пишуть архів так, як його називають у документах.
_CYR_REPO = {"ДАХМО": "DAHMO", "ЦДІАК": "CDIAK", "ДАВІО": "DAVIO",
             "ДАВО": "DAVIO", "ДАОО": "DAOO", "ДАЖО": "DAZHO"}


def _ordered_cases(index: LibraryIndex,
                   scans: list[Any] | None = None,
                   unreadable: list[Unreadable] | None = None,
                   ) -> list[dict[str, Any]]:
    """Теки з карткою справи, але без кадрів — «замовлено, не завантажено».

    Бібліотека їх не бачить за побудовою (вимагає зображень або PDF), і саме через
    це сім справ ДАОО по парафії Фараонівка не потрапили у вчорашню інвентаризацію.

    Нечитаний паспорт іде в `unreadable`, як і решта шарів (аудит 29.09.2026):
    тут стояло `except Exception: continue`, і замовлена справа з битим
    `_source.json` просто зникала з реєстру — «такої справи немає» там, де
    вона замовлена й чекає кадрів.
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for scan in (_raw_scans() if scans is None else scans):
        # глибина 1 тут не бралась ніколи: `glob` починався з `*/*`
        if scan.depth < 2 or scan.path.name.startswith("_"):
            continue
        rel = str(scan.path.relative_to(ROOT)).replace("\\", "/")
        if rel in seen or rel in index.by_path:
            continue
        if not scan.sidecar:
            continue
        if scan.has_material():
            continue                      # матеріал є → це справа бібліотеки
        passport = scan.path / scan.sidecar
        try:
            meta = json.loads(passport.read_text(encoding="utf-8"))
        except Exception as exc:
            _note_unreadable(unreadable, passport, exc)
            continue
        if not isinstance(meta, dict):
            _note_unreadable(unreadable, passport, "паспорт не є JSON-об'єктом")
            continue
        seen.add(rel)
        out.append({"rel": rel, "meta": meta})
    return out


#: Позначка вивантаження: кадри знято після звірки з копією, паспорт лишився.
OFFLOAD_MARKER = "_offloaded.json"
#: Поле паспорта, яке ставить чистка «копія живе на Wikimedia Commons».
COMMONS_PURGE_FIELD = "purged_commons_verified"


def _read_json(p: Path) -> dict[str, Any]:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return d if isinstance(d, dict) else {}


def _where_from_marker(marker: Path) -> str:
    m = _read_json(marker)
    if m.get("restore"):
        return str(m["restore"])
    if m.get("drive_path"):
        return f"Google Drive: {m['drive_path']}"
    return ""


#: Поле паспорта «кадри знято, відтворюються з джерела» (качалки, що вміють
#: перекачати справу за номером скана, як Skanoteka): `how_to_restore` усередині.
DROPPED_FIELD = "pages_dropped"


def _where_from_passport(d: Path) -> str | None:
    """Звідки повернути кадри, якщо паспорт каже, що їх знято.
    None — паспорт такої позначки не має."""
    for name in ("_source.json", "source.json"):
        meta = _read_json(d / name)
        if COMMONS_PURGE_FIELD in meta:
            url = next((str(meta[k]) for k in ("commons_url", "commons_file", "url")
                        if meta.get(k) and "commons" in str(meta[k]).lower()), "")
            return f"Wikimedia Commons: {url}" if url else "Wikimedia Commons"
        if DROPPED_FIELD in meta:
            dropped = meta[DROPPED_FIELD] if isinstance(meta[DROPPED_FIELD], dict) else {}
            src = meta.get("source") if isinstance(meta.get("source"), dict) else {}
            parts = [str(dropped.get("how_to_restore") or ""), str(src.get("url") or "")]
            return " · ".join(p for p in parts if p)
    return None


def _archived(paths: list[str | None]) -> str | None:
    """Де копія кадрів справи, якщо їх знято з диска; None — не знімали.

    Ознаки три: позначка `_offloaded.json` у теці справи або на рівень нижче
    (`pages/`, плівки); поле `purged_commons_verified` у паспорті; поле
    `pages_dropped` у паспорті (кадри відтворюються з джерела). Питається
    лише для справ без кадрів, тож обхід дешевий: кілька сотень тек, а не
    дерево `data/raw`. Повертає рядок відновлення; порожній рядок — ознака є,
    а куди поклали, не записано.
    """
    for rel in paths:
        if not rel:
            continue
        d = ROOT / rel
        if not d.is_dir():
            continue
        try:
            subs = [p for p in d.iterdir() if p.is_dir()]
        except OSError:
            subs = []
        for marker in [d / OFFLOAD_MARKER, *(s / OFFLOAD_MARKER for s in subs)]:
            if marker.is_file():
                return _where_from_marker(marker)
        where = _where_from_passport(d)
        if where is not None:
            return where
    return None


#: rel-шлях (normcase) → кадрів. Заповнюється зі спільного обходу; шляхи поза
#: `data/raw` (архівний том, оголошений корінь) сюди не потрапляють і рахуються
#: прямим читанням теки.
_FRAMES_INDEX: dict[str, tuple[int, bool]] = {}


def _material_frames(n_img: int, pdf_paths: list[Any]) -> tuple[int, bool]:
    """(кадрів, чи число точне) для теки з `n_img` кадрами й такими PDF.

    🔴 Аудит 29.09.2026: для справи-PDF тут рахувався один кадр на ФАЙЛ, тож
    прогін, що зупинився на 50-й сторінці з 300, виглядав повним (50 ≥ 1).
    Тепер знаменник — сторінки PDF, порахувані тим самим `library._pdf_pages`,
    що й бібліотека (одна правда про обсяг справи, а не дві).

    Кадри є — рахуємо кадри, як бібліотека (`imgs or pdfs`): саме їх читає
    рушій. Сторінок PDF порахувати не вдалось (битий файл, немає читача, тека
    понад стелю) — лишається файловий лік, але з позначкою «неточне»: занижене
    число краще за нуль, але повноти прогону воно не доводить.
    """
    if n_img:
        return n_img, True
    if not pdf_paths:
        return 0, True
    pages = _pdf_pages(list(pdf_paths))
    return (pages, True) if pages else (len(pdf_paths), False)


def _frames_index(scans: list[Any]) -> dict[str, tuple[int, bool]]:
    out: dict[str, tuple[int, bool]] = {}
    for s in scans:
        try:
            rel = str(s.path.relative_to(ROOT)).replace("\\", "/")
        except ValueError:
            continue
        out[os.path.normcase(rel)] = _material_frames(s.n_frames, list(s.pdf_paths))
    return out


def _count_frames_exact(rel: str | None) -> tuple[int, bool]:
    """(кадрів, чи число точне) прямо в теці; для файла-PDF — його сторінки.

    ⏱ Спершу дивиться в індекс спільного обходу (`_FRAMES_INDEX`) — саме там
    лежить переважна більшість запитів. Прямий `scandir` лишається для шляхів
    поза `data/raw`: оголошені корені на архівному диску в обхід не входять.
    """
    if not rel:
        return 0, True
    hit = _FRAMES_INDEX.get(os.path.normcase(str(rel).replace("\\", "/")))
    if hit is not None:
        return hit
    p = ROOT / rel
    if p.is_file():
        suf = p.suffix.lower()
        if suf == ".pdf":
            return _material_frames(0, [p])
        return (1 if suf in IMG_EXT else 0), True
    if not p.is_dir():
        return 0, True
    names: list[str] = []
    pdfs: list[Any] = []
    try:
        with os.scandir(p) as it:
            for f in it:
                try:
                    if not f.is_file():
                        continue
                except OSError:
                    continue
                if f.name.lower().endswith(".pdf"):
                    pdfs.append(p / f.name)
                else:
                    names.append(f.name)
    except OSError:
        pass
    # 🔴 Те саме правило, що в обході (`frame_names`): тут стояв свій набір
    # розширень, і одна справа мала два знаменники — з індексу обходу (з
    # TIFF) і з прямого читання (без них), залежно від того, де лежить тека.
    return _material_frames(len(frame_names(names)), pdfs)


def _count_frames(rel: str | None) -> int:
    """Кадри в теці (для справи-PDF — сторінки), див. `_count_frames_exact`."""
    return _count_frames_exact(rel)[0]


def _frames_uncertain(row_paths: list[str | None]) -> bool:
    """Чи немає в справи точного знаменника для покриття прогону.

    Так — коли матеріал є лише у PDF, чиїх сторінок порахувати не вдалось, і
    жодна інша тека справи не дає точного числа. Тоді прогін не можна
    оголошувати повним: «прочитано 50 з 1 файла» нічого не доводить
    (аудит 29.09.2026).
    """
    counts = [_count_frames_exact(p) for p in row_paths if p]
    if any(n and exact for n, exact in counts):
        return False
    return any(n and not exact for n, exact in counts)


def _best_frames(row_paths: list[str | None]) -> int:
    """Найповніша тека справи.

    🔴 Справа часто лежить у кількох теках — оригінальні кадри, зменшені копії для
    хмари, посторінковий рендер PDF. Бібліотека рахує кадри лише по першій, і на
    ДАХмО 315-1-7864 це давало «3 кадри» (тека з PDF) при 3773 сторінках рендеру:
    покриття декоду виходило безглуздим, а «декод обірвано» — випадковим.
    """
    return max((_count_frames(p) for p in row_paths if p), default=0)


def _unfiled_material(index: LibraryIndex, known: set[str],
                      scans: list[Any] | None = None) -> list[tuple[str, int]]:
    """Теки з кадрами, які не вдалось звести до жодної справи → [(rel, кадрів)].

    🔴 Це не дрібниця обліку: 14 плівок ANRM ф.211 (13 535 кадрів) лежать на диску
    з сайдкаром, у якому є номер плівки, але немає шифри справи. Бібліотека їх не
    бачить за побудовою (не з чого зробити ключ), тож у будь-якому зведенні вони
    просто зникали — при тому, що це найбільший необроблений масив проєкту.
    """
    out: list[tuple[str, int]] = []
    seen: set[str] = set()
    for scan in (_raw_scans() if scans is None else scans):
        if scan.path.name.startswith("_"):
            continue
        rel = str(scan.path.relative_to(ROOT)).replace("\\", "/")
        if rel in known or rel in seen:
            continue
        if any(rel.startswith(k + "/") for k in known):
            continue                      # підтека вже врахованої справи/збірки
        if split_into(rel):
            continue                      # розкладено на справи — кадри враховані там
        # Сторінки PDF, а не число файлів — та сама міра, що й у справ
        # (аудит 29.09.2026).
        frames = (_material_frames(scan.n_frames, list(scan.pdf_paths))[0]
                  if scan.has_material() else 0)
        if frames:
            seen.add(rel)
            out.append((rel, frames))
    return out


def _sidecar_near(rel: str) -> dict[str, Any]:
    """Опис справи з сайдкара теки або її батьківської теки.

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
            # ⚠ Заявлений стан «ще не ототожнено» тримає сайдкар навіть без
            # назви: там нічого називати, зате є те, чим матеріал адресується
            # (номер плівки). Мовчазний пропуск повертав би такі теки в «без
            # шифри · <ім'я теки>» — тобто ховав би рішення дослідника.
            stated = bool(m.get("unidentified")) or bool(str(m.get("film") or "").strip())
            if not title and not stated:
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
                    "opys": _sidecar_opys(m),
                    "shifra": str(m.get("shifra") or "").strip(),
                    "film": str(m.get("film") or "").strip(),
                    "unidentified": bool(m.get("unidentified")),
                    "note": str(m.get("note") or m.get("why") or "").strip(),
                    "desc_source": "source_json" if name == "_source.json" else "meta_json"}
    return {}


def _to_year(v: Any) -> int | None:
    s = str(v or "").strip()[:4]
    return int(s) if s.isdigit() else None


def _clan_runs(unreadable: list[Unreadable] | None = None) -> dict[str, dict[str, Any]]:
    """Прогони пошуку роду з `clan_hunt/state.json`.

    Файла немає — пошуку ще не було, це чесний порожній стан. Файл є, але не
    читається — це вже не «пошуку не було», а «не знаю», і збірка мусить про
    це сказати (аудит 29.09.2026).
    """
    if not CLAN_STATE.is_file():
        return {}
    try:
        state = json.loads(CLAN_STATE.read_text(encoding="utf-8"))
        runs = state.get("runs", {}) if isinstance(state, dict) else None
        if not isinstance(runs, dict):
            raise ValueError("немає словника `runs`")
    except Exception as exc:
        _note_unreadable(unreadable, CLAN_STATE, exc)
        return {}
    # Окремий битий запис не мусить гасити решту прогонів.
    out: dict[str, dict[str, Any]] = {}
    for name, run in runs.items():
        if isinstance(run, dict):
            out[name] = run
        else:
            _note_unreadable(unreadable, CLAN_STATE, f"запис `{name}` не є об'єктом")
    return out


def _pages_counts(unreadable: list[Unreadable] | None = None,
                  ) -> dict[str, tuple[int, int]]:
    """key справи → (сторінок занесено, з них `full`) зі сховища `data/pages/**`.

    Нечитаний файл сховища йде в `unreadable`: інакше справа стоїть «око не
    бачило» там, де аркуші переглянуто (аудит 29.09.2026).
    """
    out: dict[str, tuple[int, int]] = {}
    if not PAGES_ROOT.is_dir():
        return out
    for f in sorted(PAGES_ROOT.glob("*/*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:
            _note_unreadable(unreadable, f, exc)
            continue
        if not isinstance(data, dict):
            # ⚠ Раніше `data.get` на списку валив УСЮ збірку.
            _note_unreadable(unreadable, f, "файл сховища не є JSON-об'єктом")
            continue
        key = str(data.get("case") or data.get("key") or "").strip()
        if not key:
            # Ім'я файла буває двох форм: `<фонд>-<спр>` і — для фондів із
            # `_OPYS_IN_KEY` — `<фонд>-<опис>-<спр>`. Доти розбиралась лише
            # перша, тож файл із описом в імені лишався без ключа й прочитані
            # аркуші тихо не рахувались.
            repo = f.parent.name.upper()
            stem = f.stem.split("-")
            if len(stem) == 2:
                key = _mk_key(repo, stem[0], stem[1]) or ""
            elif len(stem) == 3:
                key = _mk_key(repo, stem[0], stem[2], stem[1]) or ""
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


def _canon_counts() -> dict[str, dict[str, Any]]:
    """source_id → {facts, persons, scans}. Читає derived-базу, не canonical MD.

    🔴 Аркуші рахуються з `citations.page` **і** з тексту цитати/примітки («спр.99
    скан 0123»): канон ховає номери сканів не лише в `page`, і облік лише по ньому
    показував 32 аркуші з 75 (memory `clan-search-registry-and-anchors`).
    `media[]` тут не враховано — вона не має `source_id`, тож прив'язка до справи
    була б здогадом; це відома неповнота, а не забутий шар.
    """
    out: dict[str, dict[str, Any]] = {}
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
    agg: dict[str, dict[str, Any]] = defaultdict(
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


def _htr_stage(row: CaseRow, frames_known: bool = True) -> str:
    """Стан декоду справи.

    `frames_known=False` — матеріал лише у PDF, чиїх сторінок не порахувати:
    знаменника немає, тож повноти прогону не доведено, і стан `partial`, а не
    «готово» (аудит 29.09.2026). Хибне «не дочитано» коштує зайвої перевірки,
    хибне «готово» — непрочитаних аркушів, яких ніхто вже не шукатиме.
    """
    if not (row.htr_pysar or row.htr_diak or row.htr_skryba):
        return "none"
    if not frames_known:
        return "partial"
    if row.frames and row.htr_pages_max < row.frames * _COVERAGE_OK:
        return "partial"
    if row.htr_pysar and (row.htr_diak or row.htr_skryba):
        return "both"
    return "pysar" if row.htr_pysar else ("diak" if row.htr_diak else "skryba")


def _fuzzy_stage(row: CaseRow) -> str:
    """Стан пошуку роду за зростанням повноти: none → scanned → reviewed → swept.

    ⚠ `swept` (суцільне чесання всіма каналами) стоїть вище за `reviewed`: це
    сильніша заява про покриття, і справа з вердиктами всередині прочесаного
    заходу мусить лишатись прочесаною. Спершу було навпаки, і дві з чотирнадцяти
    прочесаних справ ф.315 випадали з фільтра «прочесано».
    """
    if not row.fuzzy_scanned:
        return "none"
    if row.fuzzy_swept:
        return "swept"
    return "reviewed" if row.fuzzy_reviewed else "scanned"


def _with_cards(idx: LibraryIndex, rows: dict[str, CaseRow]) -> LibraryIndex:
    """Індекс для прив'язки прогонів: бібліотека плюс картки реєстру, яких вона
    не знає, — замовлені, архівовані (кадри на копії), заведені з паспорта.

    🔴 Бібліотека бачить лише справи з кадрами. Справа, чиї кадри вивантажено
    на копію, з неї випадала, і прогін із точним `case_key` мети та
    `case_dir` на теку справи ставав «нічиїм»: картка казала «HTR: —» при
    повному тексті, тобто той самий хибний «декоду немає» (30.09.2026, ANRM
    5-2-442 і ще сотня справ ANRM після вивантаження на Drive).

    Доповнюються лише точні ключі й шляхи. Розбір імені прогону (`lookup`)
    карток не бачить навмисно: нова картка з тим самим номером справи
    зробила б неоднозначним збіг, який сьогодні однозначний, і прогін, що
    зараз прив'язаний, став би нічиїм.
    """
    extra = [r for r in rows.values() if r.key not in idx.by_key]
    if not extra:
        return idx
    out = copy.copy(idx)
    out.by_key = dict(idx.by_key)
    out.by_path = dict(idx.by_path)
    for r in extra:
        out.by_key[r.key] = {"key": r.key, "repo": r.repo, "fond": r.fond,
                             "opys": r.opys, "spr": r.spr,
                             "desc_source": r.desc_source, "frames": r.frames}
        for p in (r.path, *r.extra_paths):
            if p:
                out.by_path.setdefault(str(p).replace("\\", "/").rstrip("/"), r.key)
    return out


def collect_rows(index: LibraryIndex | None = None, *,
                 unreadable: list[Unreadable] | None = None,
                 ) -> tuple[list[CaseRow], list[Any]]:
    """Зібрати реєстр. Повертає (рядки справ, нерозв'язані прив'язки прогонів).

    `unreadable` — куди скласти файли шарів, які не вдалось прочитати (шлях +
    причина). Збірка на них не падає, але викликач мусить про них сказати:
    без цього реєстр мовчки неповний (аудит 29.09.2026).

    ⏱ Дерево `data/raw` читається раз на всю збірку (`_raw_scans`), і той самий
    зріз живить три місця, які раніше обходили його кожне своїми `glob`-ами:
    «замовлене без кадрів», «матеріал без справи» і лічильник кадрів.
    """
    idx = index or LibraryIndex()
    scans = _raw_scans()
    global _FRAMES_INDEX
    _FRAMES_INDEX = _frames_index(scans)
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
    for item in _ordered_cases(idx, scans, unreadable):
        meta, rel = item["meta"], item["rel"]
        shifra = str(meta.get("shifra") or "").strip()
        parsed = None
        m = re.search(r"(\d+)\s*[-–]\s*(\d+)\s*[-–]\s*(\w+)", shifra)
        if m:
            repo = (re.split(r"[\s\d]", shifra, maxsplit=1)[0] or "").upper() or None
            # 🔴 Код архіву в паспорті пишуть кирилицею («ЦДІАК 224-1-918»), а ключі
            #    реєстру латинські. Без цієї нормалізації замовлена справа лягала під
            #    ключем `ЦДІАК/224/918` — окремим простором імен, у який не влучає ні
            #    `cases show CDIAK/224/918`, ні прив'язка прогону в `overrides.json`.
            if repo:
                repo = _CYR_REPO.get(repo, repo)
                parsed = (repo, m.group(1).lstrip("0"), m.group(2).lstrip("0"),
                          m.group(3).lstrip("0"))
        if not parsed:
            continue
        # 🔴 Ключ будує `_mk_key`, а не f-рядок: у фондах із `_OPYS_IN_KEY`
        # (ДАХмО ф.230, ANRM ф.211) він несе опис, і зібраний руками ключ
        # `REPO/фонд/спр` там не влучає в жоден рядок реєстру.
        key = next((k for k in candidate_keys(parsed) if k in rows), None) \
            or _mk_key(parsed[0], parsed[1], parsed[3], parsed[2])
        if not key:
            continue
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
            frames = len(frame_names(p.name for p in d.iterdir() if p.is_file()))
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
    for rel, frames in _unfiled_material(idx, known_paths, scans):
        # Спершу пробуємо звести теку до вже відомої справи: рендери й зменшені
        # копії (`dahmo_315_pages/spr-7864`) — це той самий матеріал, а не новий.
        # 🔴 Не сліпо: `slug_case` часто не знає опису теки (ім'я його не несе)
        # і тоді ранжує кандидатів «сильнішим описом» — а коли опис ВІДОМИЙ з
        # обох боків і РІЗНИЙ, це фізично інша книга, а не той самий матеріал.
        parsed = parse_slug_case(rel)
        own_opys = (parsed[2] if parsed else None) or _sidecar_near(rel).get("opys")
        hit = slug_case(rel, idx)
        if hit and hit in rows and not opys_conflict(own_opys, rows[hit].opys):
            row = rows[hit]
            if rel != row.path and rel not in row.extra_paths:
                row.extra_paths.append(rel)
            if frames > row.frames:
                row.frames = frames
                row.state = "on_disk"
            continue
        # Шифра з теки читається, але справи такої бібліотека не знає — заводимо
        # її самі. Інакше ЦДІАК 224-1-864/865 (метрики М'ястківки 1752-1791)
        # лишились би «матеріалом без шифри», хоч номер справи стоїть в імені теки.
        if parsed and parsed[1] and parsed[3]:
            repo, fond, opys, spr = parsed
            side = _sidecar_near(rel)
            # опис довизначаємо до побудови ключа — у фондах із `_OPYS_IN_KEY`
            # він у ключ входить, тож зібраний без нього ключ заводить другий
            # рядок на ту саму справу.
            opys = opys or side.get("opys") or _DEFAULT_OPYS.get((repo, fond))
            key = next((k for k in candidate_keys((repo, fond, opys, spr)) if k in rows),
                       None) or _mk_key(repo, fond, spr, opys)
            if key and key in rows and opys_conflict(opys, rows[key].opys):
                # 🔴 Кандидат знайшовся, але це ІНША книга — власний ключ,
                # а не дописування в чужу: `claim_collision` реєструє рішення
                # раз і назавжди (`data/cases/opys_keys.json`).
                key = claim_collision(
                    repo, fond, opys, spr, shifra=side.get("shifra") or "",
                    holder_shifra=rows[key].shifra, holder_key=rows[key].key)
            if not key:
                continue
            if key in rows:
                row = rows[key]
                if rel != row.path and rel not in row.extra_paths:
                    row.extra_paths.append(rel)
                row.frames = max(row.frames, frames)
                continue
            label = _REPO_LABEL.get(repo, repo)
            # Шифра з паспорта — людська і сильніша за зібрану з полів, так само
            # як у бібліотеці (`shifra_hint`). Інакше справа, яка ще не потрапила
            # у знімок бібліотеки, діставала в реєстрі іншу шифру, ніж отримає
            # після перезбірки бібліотеки.
            rows[key] = CaseRow(
                key=key, repo=repo, repo_label=label, fond=fond, opys=opys, spr=spr,
                shifra=side.get("shifra") or (f"{label} {fond}-{opys}-{spr}" if opys
                                              else f"{label} {fond}-{spr}"),
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
        # 🔴 «Ще не ототожнено» і «сайдкар мовчить» — різні рядки в переліку.
        # Перший — рішення дослідника (плівка відома, фонд і опис ще ні), і
        # підпис «без шифри · <ім'я теки>» ховав саме те, чим цей матеріал
        # адресується. Тека переїжджає, ім'я нічого не каже — а номер плівки
        # каже все.
        side = _sidecar_near(rel)
        film = str(side.get("film") or "").strip()
        stated = bool(side.get("unidentified"))
        rows[key] = CaseRow(
            key=key, kind="unfiled",
            shifra=(f"плівка {film}" if stated and film else
                    "шифру ще не встановлено" if stated else f"без шифри · {name}"),
            repo=repo or None, repo_label=repo or None,
            title=side.get("title", ""), path=rel, frames=frames, state="on_disk",
            desc_source=side.get("desc_source", "disk"),
            why=(str(side.get("note") or "").strip()
                 or "шифру ще не встановлено — заявлено в паспорті теки" if stated
                 else "матеріал на диску без шифри справи — сайдкар не несе фонд/справу"),
        )

    orphans: list[Any] = []
    ridx = _with_cards(idx, rows)

    # 🔴 Прогін пошуку роду й HTR-прогін — одна Й та сама тека `reports/htr/<run>`,
    # тож і справа в них мусить бути одна. Доти HTR-гілка резолвилась із `case_dir`
    # і `case_key` мети, а clan-гілка нижче — лише з імені прогону, і вони
    # розходились: `kostel-dazho-178-51-418-1839` (ДАЖО 178-51-418, у бібліотеці
    # лежить під теками костелу) HTR-гілкою ліг у свою справу, а clan-гілкою — у
    # чужу. Наслідок найгірший з можливих для реєстру: справа, по якій пошук
    # пройдено, показувала «пошук роду: —», тобто прилад брехав саме про те,
    # заради чого існує. Тому підказки мети збираються один раз і йдуть в обидві
    # гілки.
    run_meta_hint: dict[str, tuple[str, str]] = {}

    # ── HTR ─────────────────────────────────────────────────────────────────
    for name, meta in _iter_htr_runs(unreadable):
        run_meta_hint[name] = (str(meta.get("case_dir") or ""),
                               str(meta.get("case_key") or ""))
        link = resolve_run(name, str(meta.get("case_dir") or ""), ridx,
                           meta_key=str(meta.get("case_key") or ""))
        if link.resolved_by == "vydannia":
            # Газета чи довідник — не справа архіву: у реєстрі справ їй немає
            # рядка, а в переліку нерозв'язаних вона була б шумом.
            continue
        pg = meta.get("pages") or {}
        pages = len(pg)
        chars, lines, blank = _volume(pg)
        if not link.key or link.key not in rows:
            orphans.append({"run": name, "case_dir": link.case_dir, "pages": pages,
                            "chars": chars,
                            "model": meta.get("model") or "",
                            "resolved_by": link.resolved_by, "note": link.note,
                            "key": link.key})
            continue
        row = rows[link.key]
        row.htr_runs.append(name)
        row.htr_pages_all += pages
        row.htr_chars_all += chars
        # 🔴 Обсяг береться з ТОГО САМОГО прогону, що дав `htr_pages_max`, інакше
        # «сторінок» і «символів» описували б різні читання тієї самої справи.
        # При рівних сторінках виграє більший текст: без цього вибір залежав би
        # від порядку обходу тек, тобто мовчки плавав би між перезбірками.
        if (pages, chars) >= (row.htr_pages_max, row.htr_chars_max):
            row.htr_pages_max = pages
            row.htr_chars_max = chars
            row.htr_lines_max = lines
            row.htr_pages_blank = blank
        upd = str(meta.get("updated") or "")
        if upd > row.htr_updated:
            row.htr_updated = upd
        for voice, model in _model_voice(str(meta.get("model") or ""), _engine_of(meta)):
            setattr(row, f"htr_{voice}", True)
            if pages >= getattr(row, f"htr_{voice}_pages"):
                setattr(row, f"htr_{voice}_pages", pages)
                setattr(row, f"htr_{voice}_chars", chars)
                setattr(row, f"htr_{voice}_model", model)

    # ── fuzzy-пошук роду ────────────────────────────────────────────────────
    for name, run in _clan_runs(unreadable).items():
        hint_dir, hint_key = run_meta_hint.get(name, ("", ""))
        link = resolve_run(name, hint_dir, ridx, meta_key=hint_key)
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
        if not parsed:
            continue
        # 🔴 ID джерела канону опису не несе, а ключ фонду з `_OPYS_IN_KEY` його
        # вимагає — шукаємо всіма формами, інакше картка каже «канон: фактів 0»
        # там, де канон цитує аркуш дослівно (заміряно 2026-08-25: 34 факти).
        key = next((k for k in candidate_keys(parsed) if k in rows), None)
        if key:
            by_case_sid[key].append(sid)
    for key, sids in by_case_sid.items():
        # Окремі імена в цих трьох циклах: вище в цій же функції `row` уже
        # зв'язане як CaseRow без None, тож перевіряч не бачив тутешньої гілки
        # «такої справи в реєстрі немає» — а вона тут головна.
        canon_row = rows.get(key)
        if not canon_row:
            continue
        canon_row.canon_facts = sum(canon[s]["facts"] for s in sids)
        canon_row.canon_persons = max(canon[s]["persons"] for s in sids)
        canon_row.canon_scans = sum(canon[s]["scans"] for s in sids)
        canon_row.canon_source_id = canon_row.canon_source_id or sids[0]

    # ── око ─────────────────────────────────────────────────────────────────
    for key, (noted, full) in _pages_counts(unreadable).items():
        seen_row = rows.get(key)
        if seen_row:
            seen_row.pages_noted, seen_row.pages_full = noted, full

    # ── людські вердикти ────────────────────────────────────────────────────
    for key, v in load_verdicts().items():
        verdict_row = rows.get(key)
        if verdict_row:
            verdict_row.verdict = str(v.get("verdict") or "")
            verdict_row.verdict_note = str(v.get("note") or "")

    # ── дозаповнення опису із сайдкара ──────────────────────────────────────
    # Бібліотека бере назву лише з поля `title`, а сайдкари ДАОО описують справу
    # полями `church`+`place` — тож 13 справ парафії Фараонівка стояли «без назви»
    # при повному описі поруч. Дозаповнюємо лише порожнє, нічого не перезаписуючи.
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
        # відомості церков Ольгопільського повіту»). Беремо звідти лише повіт і
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
        frames_known = True
        if row.htr_runs and row.path:
            # ⏱ Лише для справ із прогоном: знаменник потрібен тільки там, де
            # є що з ним порівнювати. Сторінки PDF рахує той самий кешований
            # читач, що й бібліотека; якщо опис справ збирався без нього,
            # файловий лік («1 кадр») тут підміняється справжніми сторінками.
            paths: list[str | None] = [row.path, *row.extra_paths]
            frames_known = not _frames_uncertain(paths)
            row.frames = max(row.frames, _best_frames(paths))
        if not row.frames and row.state == "ordered":
            where = _archived([row.path, *row.extra_paths])
            if where is not None:
                row.state = "archived"
                row.archived_to = where
        if row.frames and row.htr_pages_max and row.htr_pages_max < row.frames * _COVERAGE_OK:
            row.state = "partial"
        row.htr_stage = _htr_stage(row, frames_known)
        row.fuzzy_stage = _fuzzy_stage(row)

    return sorted(rows.values(), key=lambda r: (r.repo_label or "", r.fond or "",
                                                int(re.sub(r"\D", "", r.spr or "0") or 0))), orphans
